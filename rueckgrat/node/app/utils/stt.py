import os
from threading import Lock

import numpy as np

from app.common import get_logger
logger = get_logger()

MODELS_DIR = "/node/models"
# "final" is the accurate model for the finished sentence, "partial" the fast one for live preview
STT_MODELS = {
    "final": "faster-whisper-medium",
    "partial": "faster-whisper-small",
}
# how many transcriptions one model runs at the same time, more queue inside ctranslate2
STT_WORKERS = int(os.getenv("STT_WORKERS", "4"))


class SpeechToText:
    """faster-whisper speech recognition. Models load on the first request, not at startup."""

    def __init__(self):
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            self.device, self.compute_type = "cuda", "float16"
        else:
            self.device, self.compute_type = "cpu", "int8"
        self.models = {}
        self.load_lock = Lock()  # only guards loading, so two first requests don't load the same model twice
        logger.info(f"startup stt interface on {self.device} ({self.compute_type})")

    def _load(self, kind: str, install_path: str):
        with self.load_lock:
            if kind not in self.models:
                from faster_whisper import WhisperModel
                path = f"{MODELS_DIR}/{install_path}"
                logger.info(f"loading whisper model {path}")
                # num_workers lets several threads call transcribe() on the same model in parallel
                self.models[kind] = WhisperModel(path, device=self.device, compute_type=self.compute_type,
                                                 num_workers=STT_WORKERS)
            return self.models[kind]

    def transcribe(self, pcm16: bytes, kind: str, install_path: str) -> str:
        """pcm16: 16 kHz mono signed 16 bit little endian samples, returns the recognized text"""
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        model = self._load(kind, install_path)
        segments, _ = model.transcribe(audio, vad_filter=False)
        # segments is a lazy generator, the actual work happens while joining
        return "".join(s.text for s in segments).strip()
