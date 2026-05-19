from .job_queue import Job
from typing import Dict, Any

from app.common import Logger, ImageRequest
logger = Logger(__name__).get_logger()

class ImageJob(Job):
    def __init__(self, request: ImageRequest, infrastructure):
        super().__init__()
        self.request = request
        self.infrastructure = infrastructure
        self.response = {}
        self.waiting_for_download = True

    def on_download_finished(self):
        self.waiting_for_download = False

    def execute(self) -> None:
        try:
            image_filename = self.infrastructure.image(self.request)

            if not image_filename:
                logger.error("failed to generate image")

            self.infrastructure.download(f"/images/{image_filename}", f"/hub/images", self.on_download_finished)

            while self.waiting_for_download:
                pass

            self.response = { 
                "image": {
                    "filename": image_filename
                }
            }
        except Exception as e:
            logger.error(f"failed to execute ImageJob {repr(e)}")                    

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True