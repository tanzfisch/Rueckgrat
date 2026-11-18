"""one audio file put together from pieces on the hub's disk: the wav chunks the tts node speaks (SpeechFile) or whole
audio files (the join_files tool) are appended to a wav file, a pause between two pieces, so the audio never has to be
held at once. finish() gives it in the format asked for (.wav, .ogg, .mp3), else the wav, or Ogg Opus when it is larger
than MAX_WAV_BYTES (libsndfile through soundfile: Opus and Vorbis are royalty free BSD codecs, MP3 through LAME, LGPL, its
patents expired, see THIRD_PARTY_LICENSES.md)"""
import io
import os
import tempfile
import wave
from typing import Optional

from app.common import get_logger
logger = get_logger()

PAUSE_SECONDS = 1.0         # silence between two pieces (the texts of one text_to_speech call, the files joined)
MAX_WAV_BYTES = 5 * 1024 * 1024     # about 1.8 min of 24 kHz mono, a larger result is encoded (about 36 kbit/s, a tenth)
MAX_AUDIO_BYTES = 100 * 1024 * 1024 # the largest audio file attached or joined, about 6 hours of Ogg Opus
OPUS_RATES = (8000, 12000, 16000, 24000, 48000)     # opus encodes only these, other rates become Ogg Vorbis
ENCODE_FRAMES = 64 * 1024   # frames read at once while encoding or appending a file
SAMPLE_WIDTH = 2            # 16 bit: what the tts node speaks and every piece is converted to
WAV, OGG, MP3 = ".wav", ".ogg", ".mp3"
FORMATS = (WAV, OGG, MP3)   # the extensions finish() makes when they are asked for


class AudioFailed(Exception):
    """a piece is no audio, or a wav chunk has another format than the pieces before, or there is no audio at all"""


class AudioFile:
    """use as a context manager (its temporary files go at the end): append the pieces in order, pause() between them,
    then finish(). the first piece sets the channels and the rate, the later files are converted to them"""

    def __init__(self):
        self._dir = tempfile.TemporaryDirectory(prefix="audio_")
        self._wav_path = os.path.join(self._dir.name, "audio.wav")
        self._wav = None            # the open wave writer, made with the first piece's parameters
        self._params: Optional[tuple] = None    # (channels, sample width, rate) of the first piece
        self._frames = 0

    def __enter__(self) -> "AudioFile":
        return self

    def __exit__(self, *exc) -> None:
        if self._wav:
            self._wav.close()
        self._dir.cleanup()

    def has_audio(self) -> bool:
        return self._params is not None

    def seconds(self) -> float:
        """the length of the audio so far"""
        return self._frames / self._params[2] if self._params else 0.0

    def pause(self) -> None:
        """PAUSE_SECONDS of silence, nothing before the first piece"""
        if self._wav:
            channels, width, rate = self._params
            self._write(b"\0" * (int(rate * PAUSE_SECONDS) * channels * width))

    def append_wav(self, wav: bytes) -> None:
        """appends the frames of a 16 bit wav (a chunk the tts node spoke). AudioFailed when it has another format than
        the first piece"""
        with wave.open(io.BytesIO(wav)) as w:
            params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            frames = w.readframes(w.getnframes())
        if self._params is None:
            self._open(params)
        elif params != self._params:
            raise AudioFailed(f"has another audio format {params} than the first {self._params}")
        self._write(frames)

    def append_file(self, data: bytes, name: str) -> None:
        """appends a whole audio file (wav, ogg, mp3: what libsndfile reads) in blocks, mixed to the first piece's channels
        and resampled to its rate (linear, enough for speech). AudioFailed when it is no audio file"""
        import numpy
        import soundfile    # only here: the hub loads its tools also without it
        try:
            source = soundfile.SoundFile(io.BytesIO(data))
        except Exception:
            raise AudioFailed(f"{name} is not an audio file (wav, ogg or mp3)")
        with source:
            if self._params is None:
                self._open((source.channels, SAMPLE_WIDTH, source.samplerate))
            channels, width, rate = self._params
            if width != SAMPLE_WIDTH:
                raise AudioFailed(f"{name} can't be joined to {8 * width} bit audio, only to 16 bit")
            read = written = 0
            for block in source.blocks(blocksize=ENCODE_FRAMES, dtype="int16", always_2d=True):
                if block.shape[1] != channels:
                    mono = block.mean(axis=1, keepdims=True)
                    block = numpy.repeat(mono, channels, axis=1)
                if source.samplerate != rate:
                    # the running totals keep the blocks' lengths right, no drift over a long file
                    read += len(block)
                    count = round(read * rate / source.samplerate) - written
                    positions = numpy.linspace(0, len(block) - 1, count) if count > 0 else numpy.empty(0)
                    block = numpy.stack([numpy.interp(positions, numpy.arange(len(block)), block[:, c]) for c in range(channels)], axis=1)
                    written += count
                self._write(numpy.asarray(block).round().astype("<i2").tobytes())

    def _open(self, params: tuple) -> None:
        self._params = params
        self._wav = wave.open(self._wav_path, "wb")
        self._wav.setnchannels(params[0])
        self._wav.setsampwidth(params[1])
        self._wav.setframerate(params[2])

    def _write(self, frames: bytes) -> None:
        channels, width, _ = self._params
        self._wav.writeframes(frames)
        self._frames += len(frames) // (channels * width)

    def finish(self, extension: str = "") -> tuple[str, bytes]:
        """(the extension, the file's bytes): in the format extension asks for (one of FORMATS, any size), else the wav,
        or Ogg when it is larger than MAX_WAV_BYTES. AudioFailed when there is no audio"""
        if not self._wav:
            raise AudioFailed("there is no audio")
        self._wav.close()
        self._wav = None
        wanted = extension.lower() if extension.lower() in FORMATS else ""
        if wanted == WAV or (not wanted and os.path.getsize(self._wav_path) <= MAX_WAV_BYTES):
            with open(self._wav_path, "rb") as f:
                return WAV, f.read()
        wanted = wanted or OGG
        return wanted, self._encoded(wanted)

    def _encoded(self, extension: str) -> bytes:
        """the wav as Ogg Opus (Vorbis for a rate opus can't encode) or MP3 (Layer III), read and written in blocks"""
        import soundfile
        path = os.path.join(self._dir.name, f"audio{extension}")
        with soundfile.SoundFile(self._wav_path) as source:
            if extension == MP3:
                kind, subtype = "MP3", "MPEG_LAYER_III"
            else:
                kind, subtype = "OGG", "OPUS" if source.samplerate in OPUS_RATES else "VORBIS"
            with soundfile.SoundFile(path, "w", source.samplerate, source.channels, format=kind, subtype=subtype) as target:
                for block in source.blocks(blocksize=ENCODE_FRAMES, dtype="int16"):
                    target.write(block)
        logger.info(f"audio of {self.seconds():.0f}s: wav {os.path.getsize(self._wav_path)} bytes, "
                    f"{kind.lower()} {subtype.lower()} {os.path.getsize(path)} bytes")
        with open(path, "rb") as f:
            return f.read()
