import hashlib
import json
from .job_queue import Job
from .image_job import ImageJob, ImageRequest
from ..utils.generic_image_prompt_compiler import GenericImagePromptCompiler
from typing import Dict, Any

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

class RequestedImageJob(Job):
    def __init__(self, prompt: str, contact_id: int, db, infrastructure, conversation_id: int = None):
        super().__init__()
        self.prompt = prompt
        self.contact_id = contact_id
        self.conversation_id = conversation_id
        self.db = db
        self.infrastructure = infrastructure
        self.response = None
        self._request = None    # built once by build_request(), the llm prompt rewrite is not repeatable

    def build_request(self) -> ImageRequest:
        """llm prompt rewrite + image settings, output stays "". built once and cached, because the
        llm gives a different prompt every call. returns a copy, so the tool (attachment) and execute()
        get the same request and hash, and execute() can set .output without touching the cache"""
        if self._request is not None:
            return self._request.model_copy()

        compiler = GenericImagePromptCompiler(self.prompt, self.infrastructure, 10, 1337)
        positive_prompt, negative_prompt = compiler.build()

        image_request = ImageRequest(
            positive_prompt = positive_prompt,
            negative_prompt = negative_prompt,
            seed = 1337,
            width = 1024,
            height = 768,
            steps = 30.0,
            cfg = 5.0,
            model = "DreamShaperXL_Turbo_V2-SFW",
            output = ""
        )
        self._request = image_request
        return self._request.model_copy()

    def execute(self) -> None:
        try:
            image_request = self.build_request()

            image_gen_hash = Utils.hash_image_request(image_request)
            self.output_file = f"{image_gen_hash}.png"
            self.db.add_contact_image(self.contact_id, self.output_file, "conversation_images")
            image_request.output = self.output_file

            image_job = ImageJob(image_request, self.infrastructure, self.db)
            self.add_sub_job(image_job)
            self.wait_for([image_job])

            self.response = image_job.result()
            if not self.response:
                logger.error("failed to generate assistant image")

        except Exception as e:
            logger.error(f"failed to execute image request {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.response