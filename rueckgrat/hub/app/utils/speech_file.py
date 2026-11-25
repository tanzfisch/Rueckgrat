"""one audio file spoken from texts of any length (the text_to_speech tool): each text is cleaned as written text (SpeechText.
written: every word, the asides too, no markdown) and cut into sentence chunks like the chat's speech, every
chunk is spoken by the tts node and appended to an AudioFile (on the hub's disk, a pause between two texts), so neither the
text nor the audio has to be held at once. the format: AudioFile.finish"""
from app.common.text_chunker import TextChunker
from app.common.speech_text import SpeechText
from app.utils.audio_file import AudioFile, AudioFailed

MAX_CHUNK_WORDS = 80        # a chunk without a sentence end is cut here, the tts model speaks about 40 s at once


class SpeechFailed(Exception):
    """the tts node could not speak a chunk (not available, or it failed), or there was nothing to speak"""


class SpeechFile:
    """use as a context manager (its temporary files go at the end): speak() every text in order, then finish()"""

    def __init__(self, infrastructure, voice: str = "", language: str = "", background: bool = False):
        """background: no one waits for the file (Infrastructure.tts)"""
        self._infrastructure = infrastructure
        self._background = background
        self._voice = voice
        self._language = language
        self._audio = AudioFile()
        self._chunks = 0
        self._texts = 0

    def __enter__(self) -> "SpeechFile":
        return self

    def __exit__(self, *exc) -> None:
        self._audio.__exit__(*exc)

    @staticmethod
    def chunks(text: str) -> list[str]:
        """what of text is spoken (SpeechText.written), cut at sentence ends like the chat's speech"""
        return TextChunker.split(SpeechText(text).written(), TextChunker.MIN_WORDS, MAX_CHUNK_WORDS)

    def speak(self, text: str) -> None:
        """appends the speech of text, after a pause when a text was spoken before. SpeechFailed when a chunk can't be spoken"""
        chunks = self.chunks(text)
        if not chunks:
            return
        if self._texts:
            self._audio.pause()
        self._texts += 1
        for chunk in chunks:
            self._append(self._infrastructure.tts(chunk, self._voice, self._language, cache=False, background=self._background))

    def _append(self, wav: bytes | None) -> None:
        if not wav:
            raise SpeechFailed(f"speaking part {self._chunks + 1} failed" if self._infrastructure.available("tts")
                               else "text to speech is not available")
        try:
            self._audio.append_wav(wav)
        except AudioFailed as e:
            raise SpeechFailed(f"part {self._chunks + 1} {e}")
        self._chunks += 1

    def chunk_count(self) -> int:
        return self._chunks

    def seconds(self) -> float:
        """the length of the speech so far"""
        return self._audio.seconds()

    def finish(self, extension: str = "") -> tuple[str, bytes]:
        """(the extension, the file's bytes) as AudioFile.finish makes them. SpeechFailed when nothing was spoken"""
        if not self._audio.has_audio():
            raise SpeechFailed("there was no text to speak")
        return self._audio.finish(extension)
