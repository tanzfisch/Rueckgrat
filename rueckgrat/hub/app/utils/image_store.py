import threading
from pathlib import Path

from app.common import get_logger, ImageRequest
logger = get_logger()

# one lock per image file, shared by everything that generates images (ImageJob and ImageStore.ensure),
# so the same file is never generated twice at the same time
_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def file_lock(file_key: str) -> threading.Lock:
    with _file_locks_guard:
        return _file_locks.setdefault(file_key, threading.Lock())


class ImageStore:
    """
    lazy access to generated images. every image the hub generates gets its parameters stored in the
    images table (file_key -> generation). if the file is gone from disk, ensure() generates it again
    with exactly those parameters, so it gets the same content and the same file name.
    """

    def __init__(self, db, infrastructure, image_dir: str = "/hub/images"):
        self.db = db
        self.infrastructure = infrastructure
        self.image_dir = Path(image_dir)

    def path(self, file_key: str) -> Path:
        return self.image_dir / file_key

    def _lock_for(self, file_key: str) -> threading.Lock:
        # one lock per image, shared with ImageJob, so a missing image is generated only once
        return file_lock(file_key)

    def ensure(self, file_key: str) -> bool:
        """True if the image is on disk afterwards. blocks while generating, call it from a worker thread"""
        if not file_key or "/" in file_key or file_key.startswith("."):
            return False
        if self.path(file_key).exists():
            return True

        with self._lock_for(file_key):
            if self.path(file_key).exists():  # another request generated it while we waited
                return True

            generation = self.db.get_image_generation(file_key)
            if not generation:
                logger.warning(f"image {file_key} is missing and has no stored generation")
                return False

            logger.info(f"image {file_key} is missing, generating it again from the stored parameters")
            try:
                image_filename = self.infrastructure.image(ImageRequest(**generation, output=file_key))
                if not image_filename:
                    logger.error(f"failed to regenerate image {file_key}")
                    return False
                self.infrastructure.download(
                    source_path=f"images/{image_filename}",
                    download_path=str(self.image_dir),
                    asynchronous=False)
            except Exception as e:
                logger.error(f"failed to regenerate image {file_key}: {repr(e)}")
                return False

            ok = self.path(file_key).exists()
            if not ok:
                logger.error(f"regenerated image {file_key} did not arrive in {self.image_dir}")
            return ok
