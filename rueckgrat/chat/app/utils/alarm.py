import io
import math
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import uuid
import wave
from array import array
from pathlib import Path

import flet as ft

from app.common import get_logger
logger = get_logger()

RATE = 22050
RING_SECONDS = 30           # rings this long unless stopped
# the ring pattern (Hz, seconds), 0 Hz = silence. made here, no sound file: a plain two tone ring
PATTERN = ((880, 0.16), (0, 0.06), (1175, 0.16), (0, 0.06), (880, 0.16), (0, 0.06), (1175, 0.16), (0, 0.9))
FADE_SECONDS = 0.01         # no clicks at the start and end of a tone
VOLUME = 0.5


class Alarm:
    """#170 rings the app for a task with its alarm (the hub's "chat" push has "alarm": true), while the app is connected.
    the ringtone is generated (PATTERN), not a file. desktop: aplay (linux), afplay (macos), winsound (windows);
    android and the web version: flet's Audio service in the app"""
    _page = None
    _lock = threading.Lock()
    _proc = None        # aplay / afplay
    _audio = None       # flet Audio service
    _wav = None         # the ringtone, made once

    @classmethod
    def attach(cls, page: ft.Page):
        cls._page = page

    @classmethod
    def ringtone(cls) -> bytes:
        """the ring as wav bytes, RING_SECONDS long"""
        if cls._wav is None:
            samples = array("h")
            fade = int(RATE * FADE_SECONDS)
            for hz, seconds in PATTERN:
                count = int(RATE * seconds)
                for i in range(count):
                    if not hz:
                        samples.append(0)
                        continue
                    envelope = min(1.0, i / fade, (count - i) / fade)
                    samples.append(int(32767 * VOLUME * envelope * math.sin(2 * math.pi * hz * i / RATE)))
            one = samples.tobytes()
            repeats = max(1, round(RING_SECONDS / sum(seconds for _, seconds in PATTERN)))
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(one * repeats)
            cls._wav = buffer.getvalue()
        return cls._wav

    @classmethod
    def ringing(cls) -> bool:
        with cls._lock:
            return cls._proc is not None or cls._audio is not None

    @classmethod
    def ring(cls):
        """starts ringing (a ring already going goes on), never raises"""
        if cls.ringing():
            return
        try:
            if cls._page is not None and (cls._page.web or cls._page.platform.is_mobile()):
                cls._ring_in_app()
            else:
                threading.Thread(target=cls._ring_desktop, daemon=True, name="alarm").start()
        except Exception as e:
            logger.error(f"alarm: ringing failed {e!r}")

    @classmethod
    def stop(cls):
        with cls._lock:
            proc, cls._proc = cls._proc, None
            audio, cls._audio = cls._audio, None
        if proc is not None and proc.poll() is None:
            proc.kill()
        if audio is not None and cls._page is not None:
            cls._page.run_task(audio.release)
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(None, 0)

    @classmethod
    def _ring_in_app(cls):
        import flet_audio as fta

        def on_state_change(e):
            if e.state in (fta.AudioState.COMPLETED, fta.AudioState.STOPPED):
                cls.stop()

        with cls._lock:
            cls._audio = fta.Audio(src=cls.ringtone(), autoplay=True, on_state_change=on_state_change)

    @classmethod
    def _ring_desktop(cls):
        path = Path(tempfile.gettempdir()) / f"rueckgrat_alarm_{uuid.uuid4().hex}.wav"
        try:
            path.write_bytes(cls.ringtone())
            if platform.system() == "Windows":
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME)     # blocks this thread, stop() ends it
                return
            player = shutil.which("aplay") or shutil.which("afplay")
            if player is None:
                logger.info("alarm: no player (aplay, afplay) found")
                return
            with cls._lock:
                cls._proc = subprocess.Popen([player, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc = cls._proc
            proc.wait()
            with cls._lock:
                if cls._proc is proc:
                    cls._proc = None
        except Exception as e:
            logger.error(f"alarm: playback failed {e!r}")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
