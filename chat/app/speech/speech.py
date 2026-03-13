import os
import signal
import subprocess
import sys
from threading import Lock
from app.utils import backend
from pathlib import Path

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
    def speak(cls, text: str, interface: str="", voice: str="", model: str=""):
        if not text.strip():
            return

        cls.kill_current_speech()
        speech_task_path = f"{os.getcwd()}/app/speech/speech_task.py"

        if interface == "piper":
            model_path = Path(f"models/{model}/{model}.onnx")
            if not model_path.exists():
                backend.get_model(model)

            proc = subprocess.Popen(
                [sys.executable, speech_task_path, "--interface", interface, "--text", text, "--model", model_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        elif interface == "kokoro":
            # TODO

            proc = subprocess.Popen(
                [sys.executable, speech_task_path, "--interface", interface, "--text", text, "--voice", voice],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

        with cls._proc_lock:
            cls._current_proc = proc