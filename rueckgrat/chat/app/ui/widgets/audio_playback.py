"""how AudioPlayer plays its bytes: a Playback per open player, made by Playback.make for the page.
mobile and web: flet's Audio service (FletPlayback), the flutter client plays it. desktop: the flet desktop client has no
listener for flet_audio (every call times out), so the file is decoded with soundfile and played with sounddevice in this
process (LocalPlayback), like the desktop's recording (AudioStreamer) uses sounddevice. a Playback reports to the player
through the callbacks it gets: on_duration(ms), on_position(ms), on_completed(), on_paused(), on_failed(text)"""
import asyncio
import io
import shutil
import subprocess
import tempfile
import re
import threading

from app.common import get_logger
from app.utils.quiet_stderr import quiet_stderr
logger = get_logger()


class PlaybackFailed(Exception):
    """the file can't be decoded or there is no audio output"""


class Playback:
    """one file's playback. load() once, then play(ms), pause(), resume(), seek(ms); release() ends it for good"""

    def __init__(self, data: bytes, on_duration, on_position, on_completed, on_paused, on_failed):
        self._data = data
        self._on_duration = on_duration
        self._on_position = on_position
        self._on_completed = on_completed
        self._on_paused = on_paused
        self._on_failed = on_failed

    @staticmethod
    def in_app(page) -> bool:
        """the client plays the audio: mobile (like Text_To_Speech._is_mobile) and web, where this process has no speakers"""
        if page is None:
            return False
        if getattr(page, "web", False):
            return True
        p = getattr(page, "platform", None)
        return bool(p and getattr(p, "is_mobile", lambda: False)())

    @classmethod
    def make(cls, page, data: bytes, **callbacks) -> "Playback":
        kind = FletPlayback if cls.in_app(page) else LocalPlayback
        return kind(data, **callbacks)

    async def load(self) -> None:
        pass

    async def play(self, ms: int) -> None:
        raise NotImplementedError

    async def pause(self) -> None:
        raise NotImplementedError

    async def resume(self) -> None:
        raise NotImplementedError

    async def seek(self, ms: int) -> None:
        raise NotImplementedError

    async def release(self) -> None:
        raise NotImplementedError


class FletPlayback(Playback):
    """flet_audio.Audio, the speech on mobile plays the same way (Text_To_Speech._play_in_app)"""

    def __init__(self, data: bytes, **callbacks):
        super().__init__(data, **callbacks)
        import flet_audio as fta
        self._fta = fta
        self._audio = fta.Audio(src=data, autoplay=False, on_duration_change=self._duration,
                                on_position_change=self._position, on_state_change=self._state)

    @staticmethod
    def _ms(value) -> int:
        return int(value.in_milliseconds) if hasattr(value, "in_milliseconds") else int(value)

    def _duration(self, e) -> None:
        self._on_duration(self._ms(e.duration))

    def _position(self, e) -> None:
        self._on_position(self._ms(e.position))

    def _state(self, e) -> None:
        if e.state == self._fta.AudioState.COMPLETED:
            self._on_completed()
        elif e.state in (self._fta.AudioState.PAUSED, self._fta.AudioState.STOPPED):
            self._on_paused()

    async def play(self, ms: int) -> None:
        import flet as ft
        await self._audio.play(ft.Duration(milliseconds=ms))

    async def pause(self) -> None:
        await self._audio.pause()

    async def resume(self) -> None:
        await self._audio.resume()

    async def seek(self, ms: int) -> None:
        import flet as ft
        await self._audio.seek(ft.Duration(milliseconds=ms))

    async def release(self) -> None:
        await self._audio.release()


class LocalPlayback(Playback):
    """soundfile reads the bytes (wav, mp3, ogg/vorbis/opus, flac; anything else through ffmpeg if it is installed) frame
    by frame into a sounddevice output stream, the frame cursor is the position. pause stops the stream and keeps the
    cursor, seek moves it. a task on the page's loop reports the position while it plays and the end"""
    POLL_SECONDS = 0.2
    FFMPEG_TIMEOUT = 300
    # libmpg123 (libsndfile's mp3 decoder) writes its resync notes to fd 2 while it decodes: mp3 is decoded once on load
    # into an in-memory wav, quietly, so playback reads from a quiet file. bigger than this decoded: streamed as it is
    MAX_DECODED_BYTES = 512 * 1024 * 1024
    DECODE_BLOCK = 65536
    MPG123_NOISE = re.compile(rb"\[src/libmpg123/|Note: (Illegal Audio-MPEG-Header|Trying to resync|Skipped \d+ bytes)"
                              rb"|Warning: .*(mpg123|MPEG|frame)")

    def __init__(self, data: bytes, **callbacks):
        super().__init__(data, **callbacks)
        self._lock = threading.Lock()   # the stream's callback thread reads the file, seek moves it
        self._file = None               # soundfile.SoundFile, None until loaded and after release
        self._stream = None             # sounddevice.OutputStream, made on the first play
        self._frame = 0                 # the next frame the stream gets
        self._playing = False
        self._ended = False             # the callback read the last frame
        self._released = False
        self._poller = None

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def released(self) -> bool:
        return self._released

    def _open_file(self):
        import soundfile as sf
        try:
            with quiet_stderr(self.MPG123_NOISE):
                file = sf.SoundFile(io.BytesIO(self._data))
            return self._decoded(file) if file.format == "MP3" else file
        except PlaybackFailed:
            raise
        except Exception as e:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise PlaybackFailed(f"this format can't be played ({e})")
        try:    # e.g. m4a / aac: ffmpeg turns it into flac, read as above. from a file, mp4 can't be read from a pipe
            with tempfile.NamedTemporaryFile(prefix="chat_audio_") as source:
                source.write(self._data)
                source.flush()
                done = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-i", source.name, "-f", "flac", "pipe:1"],
                                      capture_output=True, timeout=self.FFMPEG_TIMEOUT, check=True)
            return sf.SoundFile(io.BytesIO(done.stdout))
        except Exception as e:
            raise PlaybackFailed(f"this format can't be played ({e})")

    def _decoded(self, mp3):
        """the mp3 as an in-memory 16 bit wav, decoded in blocks with libmpg123's notes hidden. too big: the mp3 itself"""
        import soundfile as sf
        if mp3.frames * mp3.channels * 2 > self.MAX_DECODED_BYTES:
            logger.debug("audio: mp3 too big to decode up front, streamed")
            return mp3
        buffer = io.BytesIO()
        try:
            with quiet_stderr(self.MPG123_NOISE), \
                    sf.SoundFile(buffer, "w", samplerate=mp3.samplerate, channels=mp3.channels, format="WAV",
                                 subtype="PCM_16") as wav:
                while True:     # the header's length can be wrong for a damaged file: read to the end
                    block = mp3.read(self.DECODE_BLOCK, dtype="int16", always_2d=True)
                    if len(block):
                        wav.write(block)
                    if len(block) < self.DECODE_BLOCK:
                        break
        except Exception as e:
            raise PlaybackFailed(f"the mp3 can't be decoded ({e})")
        finally:
            mp3.close()
        buffer.seek(0)
        decoded = sf.SoundFile(buffer)
        if not decoded.frames:
            decoded.close()
            raise PlaybackFailed("the mp3 has no audio")
        return decoded

    def _make_stream(self):
        import sounddevice as sd
        return sd.OutputStream(samplerate=self._file.samplerate, channels=self._file.channels, dtype="float32",
                               callback=self._fill)

    def _fill(self, outdata, frames, time, status) -> None:
        """the stream's callback thread: the next frames, silence and stop after the end"""
        with self._lock:
            data = self._file.read(frames, dtype="float32", always_2d=True) if self._file is not None else []
            count = len(data)
            outdata[:count] = data
            outdata[count:] = 0
            self._frame += count
            if count < frames:
                self._ended = True
                import sounddevice as sd
                raise sd.CallbackStop

    def _heard(self) -> int:
        """the frame playing now: the cursor less what still waits in the device's buffer"""
        lag = 0
        if self._playing and self._stream is not None and self._file is not None:
            lag = int(float(getattr(self._stream, "latency", 0) or 0) * self._file.samplerate)
        return max(0, self._frame - lag)

    def _ms(self) -> int:
        return int(self._heard() * 1000 // self._file.samplerate) if self._file is not None else 0

    async def load(self) -> None:
        try:
            self._file = await asyncio.to_thread(self._open_file)
        except PlaybackFailed as e:
            self._on_failed(str(e))
            return
        if self._released:      # closed while it loaded
            self._file.close()
            self._file = None
            return
        self._on_duration(int(self._file.frames * 1000 // self._file.samplerate))

    def _move(self, ms: int) -> None:
        if self._file is not None:
            self._move_frame(int(ms * self._file.samplerate // 1000))

    def _move_frame(self, frame: int) -> None:
        with self._lock:
            if self._file is None:
                return
            frame = max(0, min(frame, self._file.frames))
            self._file.seek(frame)
            self._frame = frame
            self._ended = False

    def _start(self) -> None:
        if self._file is None or self._released:
            return
        try:
            if self._stream is None:
                self._stream = self._make_stream()
            elif not self._stream.stopped:  # ended by CallbackStop: stopped first, then it can start again
                self._stream.stop()
            self._stream.start()
        except Exception as e:
            self._playing = False
            self._on_failed(f"no audio output ({e})")
            return
        self._playing = True
        if self._poller is None or self._poller.done():
            self._poller = asyncio.create_task(self._poll())

    def _halt(self) -> None:
        heard = self._heard()
        self._playing = False
        if self._stream is not None and not self._stream.stopped:
            self._stream.abort()    # at once, the buffered frames are dropped: the cursor goes back to what was heard
            if not self._ended:
                self._move_frame(heard)

    async def _poll(self) -> None:
        while self._playing and not self._released:
            await asyncio.sleep(self.POLL_SECONDS)
            if self._released or not self._playing:
                return
            self._on_position(self._ms())
            if self._ended:
                self._halt()
                self._on_completed()
                return

    async def play(self, ms: int) -> None:
        self._move(ms)
        self._start()

    async def pause(self) -> None:
        self._halt()
        self._on_position(self._ms())

    async def resume(self) -> None:
        self._start()

    async def seek(self, ms: int) -> None:
        self._move(ms)

    async def release(self) -> None:
        """stops the stream and closes it and the file; safe to call more than once"""
        self._released = True
        self._playing = False
        poller, self._poller = self._poller, None
        if poller is not None and not poller.done() and poller is not asyncio.current_task():
            poller.cancel()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.abort()
            except Exception as e:
                logger.error(f"stopping the audio stream failed: {e}")
            finally:
                stream.close()
        with self._lock:
            file, self._file = self._file, None
        if file is not None:
            file.close()
