from pathlib import Path

from .utils import Utils
from .logger import get_logger
logger = get_logger()

class Paths:

    @classmethod
    def get_cache_path(cls):
        if Utils.is_docker():
            return Path("/cache")
        else:
            return Path("cache")