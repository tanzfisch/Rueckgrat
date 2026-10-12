import os
import platform
import re
import shlex
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from threading import Lock

import flet as ft

from app.utils import Hub
from app.common import get_logger, Utils
logger = get_logger()


class Text_To_Speech:
    """fetches speech from the hub and plays it, in a background thread"""

    _current_proc = None  # running aplay process, if any
    _generation = 0       # bumped on every speak/kill, stale threads skip playback
    _proc_lock = Lock()
    _page = None          # flet page, needed for in-app playback on mobile
    _current_audio = None # running flet Audio service on mobile, if any
    _audio_done = None    # set when in-app playback ends

    @classmethod
    def attach(cls, page: ft.Page):
        cls._page = page

    @classmethod
    def _is_mobile(cls) -> bool:
        p = getattr(cls._page, "platform", None) if cls._page else None
        return bool(p and getattr(p, "is_mobile", lambda: False)())

    @classmethod
    def kill_current_speech(cls):
        with cls._proc_lock:
            cls._generation += 1
            proc = cls._current_proc
            cls._current_proc = None
            audio, done = cls._current_audio, cls._audio_done
        if audio and cls._page and cls._is_attached(audio):
            cls._page.run_task(audio.pause)
        if done:
            done.set()
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(None, 0)

    @classmethod
    def speak(cls, text: str, voice: str = ""):
        if not text.strip():
            return

        logger.info(f"prep speech \"{Utils.shorten(text)}\" with voice \"{voice or 'default'}\"")

        try:
            cls.kill_current_speech()
            with cls._proc_lock:
                generation = cls._generation
            args = (cls._cleanup_for_speech(text), voice, generation)
            if cls._page and cls._is_mobile():
                # run_thread sets flet's page context, so services like flet_audio.Audio register themselves.
                # mobile only: run_thread workers are not daemon threads, on desktop they would block
                # interpreter exit until aplay finished, so the atexit kill_current_speech came too late
                cls._page.run_thread(cls._run_speech, *args)
            else:
                threading.Thread(target=cls._run_speech, args=args, daemon=True).start()
        except Exception as e:
            logger.error(f"failed to run speech generation {e}")

    @staticmethod
    def _cleanup_for_speech(text: str) -> str:
        text = text.replace("*", "")
        text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
        text = re.sub(r'https?://\S+|www\.\S+', '', text).strip()
        return re.sub(r'\[IMAGE:[^\]]*\]', '', text).strip()

    @classmethod
    def _is_current(cls, generation: int) -> bool:
        with cls._proc_lock:
            return generation == cls._generation

    @classmethod
    def _run_speech(cls, text: str, voice: str, generation: int):
        wav = Hub.tts(text, voice)
        if not wav:
            logger.error("failed to get speech from hub")
            return
        if not cls._is_current(generation):
            return  # a newer speak() or a kill happened while we waited for the hub

        if cls._is_mobile():
            try:
                cls._play_in_app(wav, generation)
            except Exception as e:
                logger.error(f"failed to playback speech: {e}")
            return

        output_file = os.path.join(tempfile.gettempdir(), f"chat_speech_{uuid.uuid4()}.wav")
        try:
            Path(output_file).write_bytes(wav)
            cls._play(output_file, generation)
        except Exception as e:
            logger.error(f"failed to playback speech: {e}")
        finally:
            logger.debug("delete speech")
            Path(output_file).unlink(missing_ok=True)

    @classmethod
    def _play(cls, wav_file: str, generation: int):
        logger.debug("playback speech")
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(wav_file, winsound.SND_FILENAME)
            return

        command_aplay = ["aplay", wav_file]
        logger.debug(f"run: {shlex.join(command_aplay)}")
        with cls._proc_lock:
            if generation != cls._generation:
                return
            proc = subprocess.Popen(command_aplay, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cls._current_proc = proc
        proc.wait()
        with cls._proc_lock:
            if cls._current_proc is proc:
                cls._current_proc = None

    @classmethod
    def _play_in_app(cls, wav: bytes, generation: int):
        """mobile has no aplay, play the wav bytes with flet's Audio service instead"""
        import flet_audio as fta

        logger.debug("playback speech in app")
        done = threading.Event()

        def on_state_change(e):
            if e.state in (fta.AudioState.COMPLETED, fta.AudioState.STOPPED):
                done.set()

        audio = fta.Audio(src=wav, autoplay=True, on_state_change=on_state_change)
        with cls._proc_lock:
            if generation != cls._generation:
                return
            cls._current_audio, cls._audio_done = audio, done
        try:
            done.wait(timeout=600)  # blocks only this background thread
        finally:
            with cls._proc_lock:
                if cls._current_audio is audio:
                    cls._current_audio, cls._audio_done = None, None
            if cls._is_attached(audio):
                cls._page.run_task(audio.release)

    @staticmethod
    def _is_attached(audio) -> bool:
        try:
            return audio.page is not None
        except RuntimeError:
            return False
