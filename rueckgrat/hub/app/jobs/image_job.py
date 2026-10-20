from contextlib import nullcontext
from .job_queue import Job
from ..utils.image_store import file_lock
from typing import Dict, Any

from app.common import get_logger, ImageRequest
logger = get_logger()

class ImageJob(Job):
    def __init__(self, request: ImageRequest, infrastructure, db=None):
        super().__init__()
        self.request = request
        self.infrastructure = infrastructure
        self.db = db
        self.response = {}

    def execute(self) -> None:
        # hold the per-file lock while generating, so a /downloads request for this file waits for us
        # instead of seeing it missing and generating it a second time (ImageStore.ensure)
        lock = file_lock(self.request.output) if self.request.output else nullcontext()
        with lock:
            self._execute()

    def _execute(self) -> None:
        try:
            if self.db and self.request.output:
                self.db.save_image_generation(self.request.output, self.request.model_dump(exclude={"output"}))

            image_filename = self.infrastructure.image(self.request)
            image_path = f"images/{image_filename}"

            if not image_filename:
                logger.error("failed to generate image")
                self.response = {
                    "error": {
                        "msg": f"failed to generate image: {self.request.output}",
                        "src": f"hub"
                    }
                }
            else:
                self.infrastructure.download(
                    source_path=f"{image_path}",
                    download_path=f"/hub/images",
                    asynchronous=False)

                self.response = {
                    "image": {
                        "filename": image_filename,
                        "image_path": image_path
                    }
                }
        except Exception as e:
            logger.error(f"failed to execute ImageJob {repr(e)}")                    

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True