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
    """faster-whisper speech recognition. Models load on the first request, or earlier if preload() is called."""

    def __init__(self):
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            self.device, self.compute_type = "cuda", "float16"
        else:
            self.device, self.compute_type = "cpu", "int8"
        self.models = {}
        self.load_lock = Lock()  # only guards loading, so two first requests don't load the same model twice
        logger.info(f"startup stt interface on {self.device} ({self.compute_type})")

    def _load(self, kind: str, install_path: str, source: str = "request"):
        """source: who triggered the load ("preload" or "request"), only used for the log"""
        with self.load_lock:
            if kind not in self.models:
                from faster_whisper import WhisperModel
                path = f"{MODELS_DIR}/{install_path}"
                logger.info(f"loading whisper model {path}")
                # num_workers lets several threads call transcribe() on the same model in parallel
                self.models[kind] = WhisperModel(path, device=self.device, compute_type=self.compute_type, num_workers=STT_WORKERS)
                logger.debug(f"whisper model {STT_MODELS[kind]} ({kind}) loaded by {source}")
            return self.models[kind]

    def install(self, kind: str) -> str:
        """installs the model for kind ("final"/"partial") through the registry if it is missing.
        returns its install path (relative to MODELS_DIR). raises KeyError for an unknown kind,
        RuntimeError if the model is not in the registry or the install failed"""
        from app.utils.registry import ModelRegistry
        model_name = STT_MODELS[kind]
        registry = ModelRegistry()
        if not registry.is_installed(model_name):
            if not registry.has_model(model_name):
                logger.error(f"model {model_name} not found in registry")
                raise RuntimeError(f"stt model {model_name} not registered")
            if not registry.install_model(model_name):
                logger.error(f"Failed to install model {model_name}")
                raise RuntimeError(f"stt model {model_name} could not be installed")
        return registry.get_install_path(model_name)

    def preload(self):
        """optional warm up: install (if needed) and load every model in STT_MODELS now,
        so the first request does not wait. nothing calls this automatically. models already loaded are skipped.
        errors are raised to the caller, a model that failed stays unloaded and the first request tries again."""
        for kind in STT_MODELS:
            self._load(kind, self.install(kind), source="preload")

    def transcribe(self, pcm16: bytes, kind: str, install_path: str) -> str:
        """pcm16: 16 kHz mono signed 16 bit little endian samples, returns the recognized text"""
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        model = self._load(kind, install_path)
        segments, _ = model.transcribe(audio, vad_filter=False)
        # segments is a lazy generator, the actual work happens while joining
        return "".join(s.text for s in segments).strip()
