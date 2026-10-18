import copy
import io
import re
from pathlib import Path
from threading import Lock

import soundfile as sf
import torch

from app.common import get_logger
logger = get_logger()

VOICES_DIR = Path("/node/voices")
TTS_MODEL = "chatterbox"  # registry name, the /tts endpoint installs it on first use
MODEL_DIR = Path("/node/models/voices/chatterbox")  # install_path of TTS_MODEL in registry.json
MODEL_FILES = ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]


class TextToSpeech:
    """Chatterbox TTS. The model loads on the first request, not at startup."""

    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.default_conds = None  # chatterbox built-in voice, saved before any voice overwrites it
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
            self.default_conds = copy.deepcopy(self.model.conds)
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
            voice_path = self._voice_path(voice)
            if voice_path is None:
                # chatterbox keeps the last voice in model.conds, so without this an empty voice would reuse it
                model.conds = copy.deepcopy(self.default_conds)
            logger.info("generate audio")
            wav = model.generate(
                text,
                audio_prompt_path=voice_path,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )
        buffer = io.BytesIO()
        sf.write(buffer, wav.squeeze(0).cpu().numpy(), model.sr, format="WAV")
        return buffer.getvalue()
