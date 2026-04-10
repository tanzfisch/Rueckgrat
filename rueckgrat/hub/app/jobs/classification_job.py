from .job_queue import Job
from ..utils.text_classification import text_classifier
from typing import Dict, Any

from app.common import Logger
logger = Logger(__name__).get_logger()

class ClassificationJob(Job):
    def __init__(self, content: str):
        super().__init__()
        self.content = content

    def execute(self) -> None:
        self.classification = {
            "classifications": text_classifier.classify(self.content)
        }

    def result(self) -> Dict[str, Any]:
        return self.classification