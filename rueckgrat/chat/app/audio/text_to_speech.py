import os
import signal
import subprocess
import sys
import shlex
from threading import Lock
from app.utils import Hub

from app.common import get_logger, Utils
logger = get_logger()


class Text_To_Speech:
    _current_proc = None
    _proc_lock = Lock()

    @classmethod
    def kill_current_speech(cls):
        with cls._proc_lock:
            if cls._current_proc and cls._current_proc.poll() is None:
                os.killpg(cls._current_proc.pid, signal.SIGKILL)
                cls._current_proc.wait()

    @classmethod
    def speak(cls, text: str, model: str = ""):
        if not text.strip():
            return

        logger.info(f"prep speech \"{Utils.shorten(text)}\" with {model}")

        try:
            cls.kill_current_speech()

            command = [
                sys.executable, "-m", "app.audio.text_to_speech_task",
                "--text", text,
                "--model", model,
                "--hub-url", Hub.url,
                "--token", Hub.access_token,
                "--cert", str(Hub.server_cert or ""),
            ]
            logger.debug(f"run: {shlex.join(command)}")
            proc = subprocess.Popen(
                command,
                cwd=os.getcwd(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            with cls._proc_lock:
                cls._current_proc = proc
        except Exception as e:
            logger.error(f"failed to run speech generation {e}")
