import os
from threading import Lock

from app.common import get_logger, Utils
from app.common.text_chunks import split_into_chunks
logger = get_logger()

# the state is scored chunk by chunk, each question keeps its best answer over all chunks
MIN_CHUNK_WORDS = 8     # about 50 chars, so short sentences are scored on their own, like the old splitter
MAX_CHUNK_WORDS = 150   # about 1500 chars / 350 tokens, a run-on text without sentence ends is cut there
MODELS_DIR = "/node/models"
DECISION_MODEL = "laya"   # registry.json entry, loaded with the laya package


class DecisionModel:
    """Laya typed decisions (choice / score / noul = yes-no) about a text, all questions in one forward pass.
    Strictly offline: the model files come from the registry install path, never from the hugging face cache.
    The model loads on the first request, or earlier with preload()."""

    def __init__(self):
        os.environ["HF_HUB_OFFLINE"] = "1"   # before laya imports huggingface_hub
        self.agent = None
        self.load_lock = Lock()
        self.predict_lock = Lock()   # one forward pass at a time
        logger.info("startup decision interface")

    def _load(self, source: str = "request"):
        with self.load_lock:
            if self.agent is None:
                from app.utils.registry import ModelRegistry
                registry = ModelRegistry()
                if not registry.is_installed(DECISION_MODEL):
                    logger.info(f"installing {DECISION_MODEL} for decisions ...")
                    if not registry.install_model(DECISION_MODEL):
                        raise RuntimeError(f"decision model {DECISION_MODEL} not installed")
                import laya
                path = f"{MODELS_DIR}/{registry.get_install_path(DECISION_MODEL)}"
                self.agent = laya.load(path)
                logger.info(f"decision model {path} loaded on {self.agent.device} by {source}")
            return self.agent

    def preload(self):
        """optional warm up, errors go to the caller and the first request tries again"""
        self._load(source="preload")

    def decide(self, state: str, questions: dict) -> dict:
        """questions: {id: {"type": "choice"|"score"|"noul", "instructions": ..., "criteria": ...}}
        returns laya's answers by id, e.g. {"id": {"type": "noul", "noul": P(true), ...}}"""

        agent = self._load()
        best = {}

        #logger.debug(f"all answers:\n{Utils.pretty_print(questions)}")

        chunks = split_into_chunks(state, MIN_CHUNK_WORDS, MAX_CHUNK_WORDS)
        for chunk in chunks:
            with self.predict_lock:
                partial = agent.predict(chunk, questions)
            if partial.get("usage", {}).get("truncated"):
                logger.warning("decision state was truncated to the model context")

            for tool, info in partial.get("answers", {}).items():
                if tool not in best or info.get("noul", 0) > best[tool].get("noul", 0):
                    best[tool] = info

        #logger.debug(f"all answers:\n{Utils.pretty_print(best)}")
        return best
