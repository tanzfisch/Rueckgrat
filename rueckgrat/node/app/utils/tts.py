import io
import re
from pathlib import Path
from threading import Lock

import soundfile as sf
import torch

from app.common import get_logger
logger = get_logger()

VOICES_DIR = Path("/node/data/voices")
MODEL_DIR = Path("/node/models/voices/chatterbox")  # installed via registry.json
MODEL_FILES = ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]


class TextToSpeech:
    """Chatterbox TTS. The model loads on the first request, not at startup."""

    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.lock = Lock()
        logger.info(f"startup tts interface on {self.device}")

    def _load(self):
        if self.model is None:
            from chatterbox.tts import ChatterboxTTS
            logger.info("loading chatterbox model")
            if all((MODEL_DIR / f).exists() for f in MODEL_FILES):
                self.model = ChatterboxTTS.from_local(MODEL_DIR, self.device)
            else:
                logger.warning(f"chatterbox model not found in {MODEL_DIR}, downloading from huggingface")
                self.model = ChatterboxTTS.from_pretrained(device=self.device)
        return self.model

    @staticmethod
    def _voice_path(voice: str) -> str | None:
        """voice id -> reference wav in VOICES_DIR, None = chatterbox default voice"""
        if not voice or not re.fullmatch(r"[\w.-]+", voice):
            return None
        path = VOICES_DIR / f"{voice}.wav"
        if not path.exists():
            logger.warning(f"voice {voice} not found, using default voice")
            return None
        return str(path)

    def speak(self, text: str, voice: str = "", exaggeration: float = 0.5, cfg_weight: float = 0.5) -> bytes:
        """returns the speech as wav file bytes"""
        with self.lock:  # one generation at a time on the gpu
            model = self._load()
            logger.info("generate audio")
            wav = model.generate(
                text,
                audio_prompt_path=self._voice_path(voice),
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )
        buffer = io.BytesIO()
        sf.write(buffer, wav.squeeze(0).cpu().numpy(), model.sr, format="WAV")
        return buffer.getvalue()
