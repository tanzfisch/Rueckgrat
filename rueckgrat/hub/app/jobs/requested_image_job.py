from .job_queue import Job
from .image_job import ImageJob, ImageRequest
from ..utils.generic_image_prompt_compiler import GenericImagePromptCompiler
from typing import Dict, Any

from app.common import Logger, ChatRequest, Utils
logger = Logger(__name__).get_logger()

class RequestedImageJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.response = None

    def execute(self) -> None:        
        try:
            compiler = GenericImagePromptCompiler(self.request.content, self.infrastructure, 10)
            positive_prompt, negative_prompt = compiler.build()

            # generate profile image
            image_request = ImageRequest(
                positive_prompt = positive_prompt,
                negative_prompt = negative_prompt,
                seed = 1337,
                width = 1280,
                height = 720,
                steps = 40.0,
                cfg = 11.0,
                model = "default",
                output = ""
            )

            image_gen_hash = Utils.hash_image_request(image_request)
            self.output_file = f"{image_gen_hash}.png"
            self.db.add_contact_image(self.request.contact_id, self.output_file, "gallery")
            image_request.output = self.output_file

            image_job = ImageJob(image_request, self.infrastructure)
            self.create_and_add(image_job)
            self.wait_for([image_job])

            self.response = image_job.result()
            if not self.response:
                logger.error("failed to generate assistant image")

        except Exception as e:
            logger.error(f"failed to execute image request {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.response