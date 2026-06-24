from pathlib import Path

from app.common import get_logger, Utils
logger = get_logger()

class Paths:
    @staticmethod
    def get_cache_base_path():
        return Path("/chat/cache") if Utils.is_docker() else Path("../../cache")

    @staticmethod
    def get_image_path():
        return Paths.get_cache_base_path() / "images"

    @staticmethod
    def get_models_base_path():
        return Path("/chat/models") if Utils.is_docker() else Path("../../models")    
    
    @staticmethod
    def get_voices_path():
        return Paths.get_models_base_path() / "voices"