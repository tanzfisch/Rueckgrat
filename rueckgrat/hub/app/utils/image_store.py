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


# images whose conversation got deleted (ImageStore.release). a job may still be generating such an image,
# so the job that finishes it drops it again (discard_if_released) instead of leaving an orphan file
_released: set[str] = set()


def _valid_key(file_key: str) -> bool:
    """a plain file name inside the image dir, no paths"""
    return bool(file_key) and "/" not in file_key and "\\" not in file_key and not file_key.startswith(".")


def _unlink(image_dir: Path, file_key: str) -> bool:
    """deletes image_dir/file_key, a missing file is fine. never touches anything outside image_dir.
    the caller holds the file lock"""
    if not _valid_key(file_key):
        logger.warning(f"refusing to remove invalid image key {file_key!r}")
        return False

    path = (image_dir / file_key).resolve()
    if path.parent != image_dir.resolve():
        logger.warning(f"refusing to remove {path}, it is outside of {image_dir}")
        return False

    try:
        path.unlink(missing_ok=True)
        return True
    except Exception as e:
        logger.error(f"failed deleting image {file_key}: {repr(e)}")
    return False


def discard_if_released(file_key: str, db, image_dir: str = "/hub/images") -> bool:
    """called by ImageJob when it is done, while it still holds the file lock. if the conversation of the image
    was deleted meanwhile, the rows the job wrote and the file go again, unless the image got used again
    (attachment, profile). True if the image was dropped"""
    with _file_locks_guard:
        if file_key not in _released:
            return False
        _released.discard(file_key)

    if file_key in db.release_images([file_key]):
        logger.info(f"conversation of image {file_key} was deleted while generating, removing it")
        return _unlink(Path(image_dir), file_key)
    return False


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

    @staticmethod
    def _valid_key(file_key: str) -> bool:
        """a plain file name inside image_dir, no paths"""
        return _valid_key(file_key)

    def ensure(self, file_key: str) -> bool:
        """True if the image is on disk afterwards. blocks while generating, call it from a worker thread"""
        if not self._valid_key(file_key):
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

    def remove(self, file_key: str) -> bool:
        """deletes the image file, a missing file is fine. never touches anything outside image_dir"""
        if not self._valid_key(file_key):
            logger.warning(f"refusing to remove invalid image key {file_key!r}")
            return False

        # same lock as ensure() and ImageJob. if the image is being generated right now we don't wait,
        # that could block the caller for minutes. release() marked it, so the job removes it when done
        lock = self._lock_for(file_key)
        if not lock.acquire(blocking=False):
            logger.info(f"image {file_key} is being generated, it gets removed when the generation is done")
            return False
        try:
            return _unlink(self.image_dir, file_key)
        finally:
            lock.release()

    def release(self, file_keys: list[str], drop_conversation_images: bool = True) -> list[str]:
        """drops the images in file_keys nobody refers to anymore (db rows and files). best effort, never raises,
        a leftover file is harmless. returns the released file keys, clients can drop them from their cache"""
        released = []
        try:
            released = self.db.release_images(file_keys, drop_conversation_images)
            for file_key in released:
                # marked first, so a job generating it right now (or later) drops it when done
                if self._valid_key(file_key):
                    with _file_locks_guard:
                        _released.add(file_key)
                if self.remove(file_key):
                    logger.debug(f"removed image {file_key}")
        except Exception as e:
            logger.error(f"failed releasing images: {repr(e)}")
        return released
