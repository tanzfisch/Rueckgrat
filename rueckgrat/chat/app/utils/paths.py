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
    def remove_cached_images(file_keys: list[str]):
        """deletes cached images, missing files are fine. never touches anything outside the image cache"""
        image_dir = Paths.get_image_path().resolve()
        for file_key in file_keys or []:
            if not isinstance(file_key, str) or not file_key or "/" in file_key or "\\" in file_key or file_key.startswith("."):
                logger.warning(f"refusing to remove invalid cached image {file_key!r}")
                continue
            path = (image_dir / file_key).resolve()
            if path.parent != image_dir:
                logger.warning(f"refusing to remove {path}, it is outside of {image_dir}")
                continue
            try:
                path.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"failed removing cached image {file_key}: {repr(e)}")

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