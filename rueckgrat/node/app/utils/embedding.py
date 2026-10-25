import os
from threading import Lock

from app.common import get_logger
logger = get_logger()

MODELS_DIR = "/node/models"
EMBEDDING_MODEL = "bge-small-en-v1.5"   # registry.json entry, its "embedding" block names the fastembed model and the dimensions
# bge's instruction for short search queries against stored passages. fastembed's query_embed doesn't add it for this model
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class TextEmbedder:
    """fastembed text embeddings, strictly offline: the model files must already be in the registry install path
    (no download, also not through the registry). The model loads on the first request, or earlier with preload()."""

    def __init__(self):
        os.environ["HF_HUB_OFFLINE"] = "1"   # before fastembed imports huggingface_hub
        self.model = None
        self.dims = None
        self.load_lock = Lock()
        logger.info("startup embedding interface")

    def _load(self, source: str = "request"):
        with self.load_lock:
            if self.model is None:
                from app.utils.registry import ModelRegistry
                registry = ModelRegistry()
                model = registry.get_model(EMBEDDING_MODEL)
                if not model:
                    raise RuntimeError(f"embedding model {EMBEDDING_MODEL} not registered")
                path = f"{MODELS_DIR}/{model['install_path']}"

                if not registry.is_installed(EMBEDDING_MODEL):
                    logger.info(f"installing {EMBEDDING_MODEL} for embedding ...")
                    if not registry.install_model(EMBEDDING_MODEL):
                        logger.error(f"failed to install {EMBEDDING_MODEL}")
                        raise RuntimeError(f"embedding model {EMBEDDING_MODEL} not installed")
                from fastembed import TextEmbedding
                self.model = TextEmbedding(model["embedding"]["fastembed_model"], specific_model_path=path, local_files_only=True)
                self.dims = model["embedding"]["dims"]
                logger.info(f"embedding model {path} loaded by {source}")
            return self.model

    def preload(self):
        """optional warm up, errors go to the caller and the first request tries again"""
        self._load(source="preload")

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        """one vector per text. query=True for search queries, False for stored passages"""
        model = self._load()
        if query:
            vectors = model.query_embed([QUERY_PREFIX + t for t in texts])
        else:
            vectors = model.passage_embed(texts)
        result = [v.tolist() for v in vectors]
        if any(len(v) != self.dims for v in result):
            raise RuntimeError(f"embedding model returned other than {self.dims} dimensions")
        return result
