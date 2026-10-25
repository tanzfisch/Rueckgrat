"""text embeddings for the memories. the node embeds (service text_to_embedding, bge-small-en-v1.5 from its registry),
the hub only stores the vectors in sqlite-vec and searches them"""
from typing import List, Optional

from app.common import get_logger
from app.utils.db import MEMORY_EMBEDDING_DIM
logger = get_logger()

def embed_text(infrastructure, text: str, query: bool = False) -> Optional[List[float]]:
    """the vector of text with MEMORY_EMBEDDING_DIM floats, None without an embedding node or if it fails.
    query=True for a search query, False for a memory that is stored"""
    vectors = infrastructure.embed([text], query=query) if infrastructure else None
    if not vectors:
        return None
    if len(vectors[0]) != MEMORY_EMBEDDING_DIM:
        logger.error(f"embedding has {len(vectors[0])} dimensions, the memory index needs {MEMORY_EMBEDDING_DIM}")
        return None
    return vectors[0]
