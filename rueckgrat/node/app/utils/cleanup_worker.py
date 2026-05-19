import time
import threading
from pathlib import Path
from contextlib import asynccontextmanager

from app.common import Logger
logger = Logger(__name__).get_logger()

class CleanupWorker:
    def __init__(
        self,
        folder: str,
        max_file_age_seconds: int = 60 * 60,
        cleanup_interval_seconds: int = 10 * 60,
    ):
        self.folder = Path(folder)
        self.max_file_age_seconds = max_file_age_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds

        self.stop_event = threading.Event()

        self.thread = threading.Thread(
            target=self.run,
            daemon=True,
        )

    def start(self):
        self.thread.start()
        logger.info("Cleanup worker started")

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
        logger.info("Cleanup worker stopped")
      
    def run(self):
        while not self.stop_event.is_set():
            now = time.time()

            try:
                for file_path in self.folder.iterdir():
                    if file_path.is_file():
                        file_age = now - file_path.stat().st_mtime

                        if file_age > self.max_file_age_seconds:
                            try:
                                file_path.unlink()
                                logger.debug(f"Deleted: {file_path}")
                            except Exception as e:
                                logger.error(f"Failed to delete {file_path}: {e}")

            except Exception as e:
                logger.error(f"failed to run cleanup: {e}")

            self.stop_event.wait(self.cleanup_interval_seconds)