from pydantic import BaseModel
from .job_queue import Job
from typing import Dict, Any

from app.common import Logger, ImageRequest
logger = Logger(__name__).get_logger()

class ImageJob(Job):
    def __init__(self, request: ImageRequest, infrastructure):
        super().__init__()
        self.request = request
        self.infrastructure = infrastructure

    def execute(self) -> None:
        image_filename, size = self.infrastructure.image(self.request)

        if not image_filename or not size:
            logger.error("failed to generate image")

        self.response = {
            "filename": image_filename,
            "file_size": size
        }

    def result(self) -> Dict[str, Any]:
        return self.response