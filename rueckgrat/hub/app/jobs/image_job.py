from .job_queue import Job
from typing import Dict, Any

from app.common import get_logger, ImageRequest
logger = get_logger()

class ImageJob(Job):
    def __init__(self, request: ImageRequest, infrastructure):
        super().__init__()
        self.request = request
        self.infrastructure = infrastructure
        self.response = {}

    def execute(self) -> None:
        try:
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
                    source_path=f"/{image_path}", # todo why the extra /
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