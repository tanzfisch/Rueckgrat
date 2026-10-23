import base64
import io
import threading
import wave
from collections import deque

from app.common import get_logger
from app.common.text_chunks import split_into_chunks
logger = get_logger()

PIECE_SECONDS = 1          # audio goes to the client in pieces of this length, like the #112 mic buffer
MAX_QUEUED_PIECES = 300    # per reply, 5 min of audio the client has not confirmed yet
FULL_WAIT_SECONDS = 120    # a full queue pauses the generation, the reply is dropped if it stays full this long


def wav_pieces(wav: bytes, chunk: int) -> list[dict]:
    """splits one generated wav into PIECE_SECONDS pieces of raw pcm, "last" marks the end of the text chunk"""
    with wave.open(io.BytesIO(wav)) as w:
        params = {"rate": w.getframerate(), "channels": w.getnchannels(), "width": w.getsampwidth()}
        frames = w.readframes(w.getnframes())
    size = params["rate"] * params["channels"] * params["width"] * PIECE_SECONDS
    parts = [frames[i:i + size] for i in range(0, len(frames), size)] or [b""]
    return [{**params, "chunk": chunk, "last": i == len(parts) - 1, "data": base64.b64encode(part).decode()}
            for i, part in enumerate(parts)]


class TtsReply:
    """the audio pieces of one spoken reply, numbered by seq. a piece stays queued until the client
    acknowledged it, so after a reconnect the hub sends everything from the client's last seq on"""

    def __init__(self, reply_id: str, message_id):
        self.reply_id = reply_id
        self.message_id = message_id
        self.pieces = deque()
        self.next_seq = 0
        self.dropped = threading.Event()
        self.cond = threading.Condition()

    def put(self, piece: dict) -> bool:
        """queues a piece, waits while the queue is full. False if the reply was dropped"""
        with self.cond:
            if not self.cond.wait_for(lambda: len(self.pieces) < MAX_QUEUED_PIECES or self.dropped.is_set(), FULL_WAIT_SECONDS):
                logger.warning(f"tts reply {self.reply_id}: queue full for {FULL_WAIT_SECONDS}s, dropping it")
                self.dropped.set()
            if self.dropped.is_set():
                return False
            self.pieces.append({**piece, "seq": self.next_seq})
            self.next_seq += 1
            return True

    def after(self, seq: int) -> list[dict]:
        """the queued pieces after seq, in order"""
        with self.cond:
            return [piece for piece in self.pieces if piece["seq"] > seq]

    def ack(self, seq: int) -> bool:
        """the client has every piece up to seq: they are removed. True once the end of the reply was acknowledged"""
        with self.cond:
            finished = False
            while self.pieces and self.pieces[0]["seq"] <= seq:
                finished = bool(self.pieces.popleft().get("end"))
            self.cond.notify_all()
            return finished

    def drop(self):
        self.dropped.set()
        with self.cond:
            self.pieces.clear()
            self.cond.notify_all()


class TtsStreams:
    """the reply each user is listening to (one at a time, a new one replaces it). its audio is generated
    chunk by chunk in a thread and queued, the /ws/tts connection sends it, a reconnect resumes it"""
    _lock = threading.Lock()
    _replies = {}  # user_id -> TtsReply

    @classmethod
    def start(cls, infrastructure, user_id: int, reply_id: str, text: str, voice: str = "", message_id=None, language: str = "") -> TtsReply:
        reply = TtsReply(reply_id, message_id)
        with cls._lock:
            previous = cls._replies.get(user_id)
            cls._replies[user_id] = reply
        if previous:
            previous.drop()
        threading.Thread(target=cls._generate, args=(infrastructure, reply, text, voice, language), daemon=True).start()
        return reply

    @classmethod
    def get(cls, user_id: int, reply_id: str) -> TtsReply | None:
        with cls._lock:
            reply = cls._replies.get(user_id)
            return reply if reply and reply.reply_id == reply_id and not reply.dropped.is_set() else None

    @classmethod
    def stop(cls, user_id: int, reply_id: str):
        """the client stopped the speech, or the reply is complete"""
        with cls._lock:
            reply = cls._replies.get(user_id)
            if not reply or reply.reply_id != reply_id:
                return
            del cls._replies[user_id]
        reply.drop()

    @classmethod
    def drop_message(cls, message_id):
        """the chat reply was cancelled (a follow-up merged into its turn), its speech goes too"""
        with cls._lock:
            dropped = [(user_id, reply) for user_id, reply in cls._replies.items() if reply.message_id == message_id]
            for user_id, _ in dropped:
                del cls._replies[user_id]
        for _, reply in dropped:
            reply.drop()

    @staticmethod
    def _generate(infrastructure, reply: TtsReply, text: str, voice: str, language: str):
        chunks = split_into_chunks(text)
        logger.info(f"tts reply {reply.reply_id}: {len(chunks)} chunk(s)")
        for index, chunk in enumerate(chunks):
            if reply.dropped.is_set():
                return
            wav = infrastructure.tts(chunk, voice, language)
            if not wav:
                logger.error(f"tts reply {reply.reply_id}: chunk {index} failed, skipping it")
                continue
            for piece in wav_pieces(wav, index):
                if not reply.put(piece):
                    return
        reply.put({"end": True})
