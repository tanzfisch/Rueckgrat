import base64
import io
import threading
import wave
from collections import deque

from app.common import get_logger
import time
from app.common.text_chunker import TextChunker
from app.common.speech_text import SpeechText
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

    def __init__(self, reply_id: str, message_id, text: str = "", final: bool = True):
        self.reply_id = reply_id
        self.message_id = message_id
        self.text = text        # the reply's text so far
        self.final = final      # False while the reply is still streaming, set_text hands over the rest
        self.text_version = 0
        self.text_cond = threading.Condition()
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

    def set_text(self, text: str, final: bool):
        """the reply's text so far (the whole of it, not the new part), final once it is complete"""
        with self.text_cond:
            if self.final:
                return
            self.text, self.final = text, final
            self.text_version += 1
            self.text_cond.notify_all()

    def latest(self) -> tuple[str, bool, int]:
        """(text, final, version) right now"""
        with self.text_cond:
            return self.text, self.final, self.text_version

    def wait_text(self, version: int) -> tuple[str, bool, int]:
        """(text, final, version) once the text is newer than version, it is complete or the reply was dropped"""
        with self.text_cond:
            self.text_cond.wait_for(lambda: self.text_version != version or self.final or self.dropped.is_set(), FULL_WAIT_SECONDS)
            return self.text, self.final, self.text_version

    def drop(self):
        self.dropped.set()
        with self.cond:
            self.pieces.clear()
            self.cond.notify_all()
        with self.text_cond:
            self.text_cond.notify_all()


class TtsStreams:
    """the reply each user is listening to (one at a time, a new one replaces it). its audio is generated
    chunk by chunk in a thread and queued, the /ws/tts connection sends it, a reconnect resumes it"""
    _lock = threading.Lock()
    _replies = {}  # user_id -> TtsReply

    @classmethod
    def start(cls, infrastructure, user_id: int, reply_id: str, text: str, voice: str = "", message_id=None, language: str = "",
              final: bool = True) -> TtsReply:
        """final False: the reply is still streaming, TtsReply.set_text hands over the rest"""
        reply = TtsReply(reply_id, message_id, text, final)
        with cls._lock:
            previous = cls._replies.get(user_id)
            cls._replies[user_id] = reply
        if previous:
            previous.drop()
        threading.Thread(target=cls._generate, args=(infrastructure, reply, voice, language), daemon=True).start()
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
    def _generate(infrastructure, reply: TtsReply, voice: str, language: str):
        """speaks every chunk as soon as it is complete (TextChunker.words_for). while the reply streams the last chunk may still
        grow, it waits for more text"""
        index, spoken, version = 0, 0, -1   # spoken: the words of the text already spoken
        while not reply.dropped.is_set():
            text, final, latest = reply.wait_text(version)
            if not final and latest == version:
                logger.warning(f"tts reply {reply.reply_id}: no more text for {FULL_WAIT_SECONDS}s, speaking the rest")
                final = True
            version = latest
            while not reply.dropped.is_set():
                words = SpeechText(text).without_code(final).split()[spoken:]
                chunks = TextChunker.split(" ".join(words), min_words=TextChunker.words_for(index))
                if not chunks or (len(chunks) == 1 and not final):
                    break   # nothing left, or the last chunk may not be complete yet
                spoken += len(chunks[0].split())
                if not TtsStreams._speak_chunk(infrastructure, reply, chunks[0], index, voice, language):
                    return
                index += 1
                if not final:
                    text, final, version = reply.latest()
            if final:
                logger.info(f"tts reply {reply.reply_id}: {index} chunk(s)")
                reply.put({"end": True})
                return

    @staticmethod
    def _speak_chunk(infrastructure, reply: TtsReply, chunk: str, index: int, voice: str, language: str) -> bool:
        """generates and queues the speech of one chunk. False if the reply was dropped"""
        speech = SpeechText(chunk).reply()
        if not speech:
            return True
        started = time.perf_counter()
        wav = infrastructure.tts(speech, voice, language)
        if not wav:
            logger.error(f"tts reply {reply.reply_id}: chunk {index} failed, skipping it")
            return True
        pieces = wav_pieces(wav, index)
        logger.debug(f"tts reply {reply.reply_id}: chunk {index} ({len(speech.split())} words) took {time.perf_counter() - started:.2f}s "
                     f"for {len(pieces) * PIECE_SECONDS}s of audio")
        return all(reply.put(piece) for piece in pieces)
