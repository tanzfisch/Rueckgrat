"""one audio file spoken from texts of any length (the text_to_speech tool): each text is cleaned as written text (text_chunks.
written_speech_text: every word, the asides too, no markdown) and cut into sentence chunks like the chat's speech, every chunk is spoken by the tts node and its wav frames are appended to a wav file on the
hub's disk, so neither the text nor the audio has to be held at once. a wav larger than MAX_WAV_BYTES is encoded as Ogg
Opus (libsndfile through soundfile: royalty free, BSD licensed codecs, see THIRD_PARTY_LICENSES.md)"""
import io
import os
import tempfile
import wave

from app.common.text_chunks import split_into_chunks, written_speech_text, MIN_CHUNK_WORDS
from app.common import get_logger
logger = get_logger()

MAX_CHUNK_WORDS = 80        # a chunk without a sentence end is cut here, the tts model speaks about 40 s at once
PAUSE_SECONDS = 1.0         # silence between two texts (the files of one call, e.g. chapters)
MAX_WAV_BYTES = 5 * 1024 * 1024     # about 1.8 min of 24 kHz mono, a larger result is encoded (about 36 kbit/s, a tenth)
OPUS_RATES = (8000, 12000, 16000, 24000, 48000)     # opus encodes only these, other rates become Ogg Vorbis
ENCODE_FRAMES = 64 * 1024   # frames read from the wav at once while encoding
WAV, OGG = ".wav", ".ogg"


class SpeechFailed(Exception):
    """the tts node could not speak a chunk (not available, or it failed), or there was nothing to speak"""


class SpeechFile:
    """use as a context manager (its temporary files go at the end): speak() every text in order, then finish()"""

    def __init__(self, infrastructure, voice: str = "", language: str = ""):
        self._infrastructure = infrastructure
        self._voice = voice
        self._language = language
        self._dir = tempfile.TemporaryDirectory(prefix="speech_")
        self._wav_path = os.path.join(self._dir.name, "speech.wav")
        self._wav = None            # the open wave writer, made with the first chunk's parameters
        self._params = None         # (channels, sample width, rate) of the first chunk, every chunk has to have them
        self._frames = 0
        self._chunks = 0
        self._texts = 0

    def __enter__(self) -> "SpeechFile":
        return self

    def __exit__(self, *exc) -> None:
        if self._wav:
            self._wav.close()
        self._dir.cleanup()

    @staticmethod
    def chunks(text: str) -> list[str]:
        """what of text is spoken (written_speech_text), cut at sentence ends like the chat's speech"""
        return split_into_chunks(written_speech_text(text), MIN_CHUNK_WORDS, MAX_CHUNK_WORDS)

    def speak(self, text: str) -> None:
        """appends the speech of text, after a pause when a text was spoken before. SpeechFailed when a chunk can't be spoken"""
        chunks = self.chunks(text)
        if not chunks:
            return
        if self._texts and self._wav:
            channels, width, rate = self._params
            self._write(b"\0" * (int(rate * PAUSE_SECONDS) * channels * width))
        self._texts += 1
        for chunk in chunks:
            self._append(self._infrastructure.tts(chunk, self._voice, self._language, cache=False))

    def _append(self, wav: bytes | None) -> None:
        if not wav:
            raise SpeechFailed(f"speaking part {self._chunks + 1} failed" if self._infrastructure.available("tts")
                               else "text to speech is not available")
        with wave.open(io.BytesIO(wav)) as w:
            params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            frames = w.readframes(w.getnframes())
        if self._wav is None:
            self._params = params
            self._wav = wave.open(self._wav_path, "wb")
            self._wav.setnchannels(params[0])
            self._wav.setsampwidth(params[1])
            self._wav.setframerate(params[2])
        elif params != self._params:
            raise SpeechFailed(f"part {self._chunks + 1} has another audio format {params} than the first {self._params}")
        self._write(frames)
        self._chunks += 1

    def _write(self, frames: bytes) -> None:
        channels, width, _ = self._params
        self._wav.writeframes(frames)
        self._frames += len(frames) // (channels * width)

    def chunk_count(self) -> int:
        return self._chunks

    def seconds(self) -> float:
        """the length of the speech so far"""
        return self._frames / self._params[2] if self._params else 0.0

    def finish(self) -> tuple[str, bytes]:
        """(extension WAV or OGG, the file's bytes): the wav, or encoded when it is larger than MAX_WAV_BYTES.
        SpeechFailed when nothing was spoken"""
        if not self._wav:
            raise SpeechFailed("there was no text to speak")
        self._wav.close()
        self._wav = None
        if os.path.getsize(self._wav_path) <= MAX_WAV_BYTES:
            with open(self._wav_path, "rb") as f:
                return WAV, f.read()
        return OGG, self._encoded()

    def _encoded(self) -> bytes:
        """the wav as Ogg Opus (Vorbis for a rate opus can't encode), read and written in blocks"""
        import soundfile    # only here: the hub loads its tools also without it
        path = os.path.join(self._dir.name, "speech.ogg")
        with soundfile.SoundFile(self._wav_path) as source:
            subtype = "OPUS" if source.samplerate in OPUS_RATES else "VORBIS"
            with soundfile.SoundFile(path, "w", source.samplerate, source.channels, format="OGG", subtype=subtype) as target:
                for block in source.blocks(blocksize=ENCODE_FRAMES, dtype="int16"):
                    target.write(block)
        logger.info(f"speech of {self.seconds():.0f}s: wav {os.path.getsize(self._wav_path)} bytes, "
                    f"ogg {subtype.lower()} {os.path.getsize(path)} bytes")
        with open(path, "rb") as f:
            return f.read()
