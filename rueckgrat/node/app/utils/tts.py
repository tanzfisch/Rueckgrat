import copy
import io
import os
import re
from pathlib import Path
from threading import Lock

import soundfile as sf
import torch

from app.common import get_logger
logger = get_logger()

VOICES_DIR = Path("/node/voices")
MODELS_BASE_DIR = Path("/node/models")  # same as MODEL_BASE_DIR in utils/registry.py

# registry name -> files from_local() needs and whether generate() takes a language
TTS_MODELS = {
    "chatterbox": {
        "files": ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"],
        "multilingual": False,
    },
    "chatterbox_multilingual": {
        "files": ["ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json", "conds.pt"],
        "multilingual": True,
    },
}

# picked in install.sh, written to the node .env, passed in by compose.yml
TTS_MODEL = os.environ.get("TTS_MODEL", "chatterbox").strip() or "chatterbox"
if TTS_MODEL not in TTS_MODELS:
    logger.warning(f"unknown TTS_MODEL {TTS_MODEL}, using chatterbox")
    TTS_MODEL = "chatterbox"
MODEL_FILES = TTS_MODELS[TTS_MODEL]["files"]
MULTILINGUAL = TTS_MODELS[TTS_MODEL]["multilingual"]

# languages ChatterboxMultilingualTTS accepts as language_id (chatterbox.mtl_tts.SUPPORTED_LANGUAGES)
MULTILINGUAL_LANGUAGES = ["ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja",
                          "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh"]
DEFAULT_LANGUAGE = "en"  # used when the text is too short or ambiguous to detect
MIN_LANGUAGE_CONFIDENCE = 0.5  # langid probability 0..1, below this DEFAULT_LANGUAGE is used


class TextToSpeech:
    """Chatterbox TTS. The model loads on the first request, or earlier if preload() is called."""

    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.model_dir = None  # set by install() from the registry install_path
        self.default_conds = None  # chatterbox built-in voice, saved before any voice overwrites it
        self.language_identifier = None  # langid detector, created on first use, multilingual only
        self.lock = Lock()
        logger.info(f"startup tts interface on {self.device}")

    def _load(self, source: str = "request"):
        """source: who triggered the load ("preload" or "request"), only used for the log"""
        if self.model is None:
            if MULTILINGUAL:
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS as Chatterbox
            else:
                from chatterbox.tts import ChatterboxTTS as Chatterbox
            logger.info(f"loading tts model {TTS_MODEL}")
            if self.model_dir and all((self.model_dir / f).exists() for f in MODEL_FILES):
                self.model = Chatterbox.from_local(self.model_dir, self.device)
            else:
                logger.warning(f"tts model {TTS_MODEL} not found in {self.model_dir}, downloading from huggingface")
                self.model = Chatterbox.from_pretrained(device=self.device)
            self.default_conds = copy.deepcopy(self.model.conds)
            logger.debug(f"tts model {TTS_MODEL} loaded by {source}")
        return self.model

    def install(self) -> Path:
        """installs TTS_MODEL through the registry if it is missing.
        returns its install dir (/node/models/<install_path>). raises RuntimeError if the model is not
        in the registry or the install failed"""
        from app.utils.registry import ModelRegistry
        registry = ModelRegistry()
        if not registry.is_installed(TTS_MODEL):
            if not registry.has_model(TTS_MODEL):
                logger.error(f"model {TTS_MODEL} not found in registry")
                raise RuntimeError(f"tts model {TTS_MODEL} not registered")
            if not registry.install_model(TTS_MODEL):
                logger.error(f"Failed to install model {TTS_MODEL}")
                raise RuntimeError(f"tts model {TTS_MODEL} could not be installed")
        self.model_dir = MODELS_BASE_DIR / registry.get_install_path(TTS_MODEL)
        return self.model_dir

    def preload(self):
        """optional warm up: install (if needed) and load the model now so the first request does not wait for it.
        nothing calls this automatically. does nothing if the model is already loaded.
        errors are raised to the caller, the model then stays unloaded and the first request tries again."""
        self.install()  # outside the lock, a download must not block running generations
        with self.lock:  # same lock as speak(), so a request never sees a half loaded model
            self._load(source="preload")

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

    def _detect_language(self, text: str) -> str:
        """language code of text, limited to MULTILINGUAL_LANGUAGES. DEFAULT_LANGUAGE if unsure"""
        if self.language_identifier is None:
            from langid.langid import LanguageIdentifier, model
            # norm_probs=True makes classify() return a 0..1 probability instead of a raw score
            self.language_identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
            self.language_identifier.set_languages(MULTILINGUAL_LANGUAGES)
        language, confidence = self.language_identifier.classify(text)
        if confidence < MIN_LANGUAGE_CONFIDENCE:
            logger.debug(f"language unsure ({language} {confidence:.2f}), using {DEFAULT_LANGUAGE}")
            return DEFAULT_LANGUAGE
        logger.debug(f"detected language {language} ({confidence:.2f})")
        return language

    def speak(self, text: str, voice: str = "", exaggeration: float = 0.5, cfg_weight: float = 0.5,
              language: str | None = None) -> bytes:
        """returns the speech as wav file bytes. language is only used by the multilingual model,
        None = detect it from the text"""
        if MULTILINGUAL and not language:
            language = self._detect_language(text)
        with self.lock:  # one generation at a time on the gpu
            model = self._load()
            voice_path = self._voice_path(voice)
            if voice_path is None:
                # chatterbox keeps the last voice in model.conds, so without this an empty voice would reuse it
                model.conds = copy.deepcopy(self.default_conds)
            logger.info("generate audio")
            # the english model has no language parameter, the multilingual one requires it
            extra = {"language_id": language} if MULTILINGUAL else {}
            wav = model.generate(
                text,
                **extra,
                audio_prompt_path=voice_path,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )
        buffer = io.BytesIO()
        sf.write(buffer, wav.squeeze(0).cpu().numpy(), model.sr, format="WAV")
        return buffer.getvalue()
