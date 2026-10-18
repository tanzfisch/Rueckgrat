import sys
from pathlib import Path

from app.common import get_logger, Utils
logger = get_logger()

class Paths:
    @staticmethod
    def get_cache_base_path():
        if sys.platform in ("android", "ios", "emscripten"):
            return Path("../../cache")
        return Path(__file__).resolve().parents[4] / "cache"

    @staticmethod
    def get_image_path():
        return Paths.get_cache_base_path() / "images"

    @staticmethod
    def image_src(image_path, web: bool) -> str | bytes:
        """src for ft.Image of a cached image: in web mode the browser loads src itself and can't reach our local cache, so send the bytes"""
        path = Path(image_path)
        if web and path.is_file():
            return path.read_bytes()
        return str(path)

    @staticmethod
    def get_models_base_path():
        return Path("/var/lib/Rueckgrat/models")
    
    @staticmethod
    def get_voices_path():
        return Paths.get_models_base_path() / "voices"