import os
import signal
import subprocess
import sys
from threading import Lock
from app.utils import Backend, Paths
from pathlib import Path

from app.common import get_logger
logger = get_logger()


class Speech:
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

        logger.debug(f"prep speech \"{text}\" with {model}")

        try:
            cls.kill_current_speech()
            speech_task_path = f"{os.getcwd()}/app/speech/speech_task.py"

            voices_base_path = Paths.get_voices_path()
            model_path = Path(f"{voices_base_path}/{model}")
            model_file_path = Path(f"{model_path}/{model}.onnx")
            model_json_file_path = Path(f"{model_path}/{model}.onnx.json")
            if not model_file_path.exists() or not model_json_file_path.exists():
                Backend.get_model(model, model_path)

            if not model_file_path.exists():
                logger.error(f"failed to retrive voice file for {model}")

            proc = subprocess.Popen(
                [sys.executable, speech_task_path, "--text", text, "--model", model_file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            with cls._proc_lock:
                cls._current_proc = proc
        except Exception as e:
            logger.error(f"failed to run speech generation {e}")
