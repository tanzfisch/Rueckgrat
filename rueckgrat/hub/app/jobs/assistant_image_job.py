from .job_queue import Job
from .image_job import ImageJob, ImageRequest
from ..utils.contact_image_prompt_compiler import ContactImagePromptCompiler, ImageType
from typing import Dict, Any

from app.common import Logger, ChatRequest, Utils
logger = Logger(__name__).get_logger()

class AssistantImageJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure, assitant_only: bool):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure
        self.response = None
        self.assitant_only = assitant_only

    def execute(self) -> None:
        contact_data = self.db.get_contact_by_id(self.request.contact_id)
        image_parameters = contact_data["profile"]["image_parameters"]

        conversation = self.db.get_conversation(self.request.conversation_id)
        context = conversation["context"]        

        if self.assitant_only:
            width = 720
            height = 1280
            user_present = False
        else:
            width = 1280
            height = 720
            user_present = True

        compiler = ContactImagePromptCompiler(contact_data, context, ImageType.FullBody, user_present)
        positive_prompt, negative_prompt = compiler.build()

        # generate profile image
        image_request = ImageRequest(
            positive_prompt = positive_prompt,
            negative_prompt = negative_prompt,
            seed = image_parameters.get("seed", 1337),
            width = width,
            height = height,
            steps = image_parameters.get("steps", 40.0),
            cfg = image_parameters.get("cfg", 8.0),
            model = image_parameters.get("model", "default"),
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

    def result(self) -> Dict[str, Any]:
        return self.response