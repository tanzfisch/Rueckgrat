from .job_queue import Job
from pathlib import Path
from .image_job import ImageJob, ImageRequest
from ..utils.contact_image_prompt_compiler import ContactImagePromptCompiler, ImageType
from typing import Dict, Any

from app.common import Logger, Utils
logger = Logger(__name__).get_logger()

class AssistantImageJob(Job):
    def __init__(self, user_id: int, contact_id: int, db, infrastructure, width: int = 720, height: int = 1280, conversation_id: int = None, show_assistant: bool = True, show_user: bool = False, image_type: ImageType = ImageType.FullBody, store_image_as: str = "gallery"):
        super().__init__()
        self.user_id = user_id
        self.contact_id = contact_id
        self.conversation_id = conversation_id
        self.db = db
        self.infrastructure = infrastructure
        self.response = None
        self.show_assistant = show_assistant
        self.show_user = show_user
        self.image_type = image_type
        self.store_image_as = store_image_as
        self.width = width
        self.height = height

    def execute(self) -> None:
        contact_data = self.db.get_contact_by_id(self.contact_id)
        user_data = self.db.get_user_data(self.user_id)
        image_parameters = contact_data["profile"]["image_parameters"]

        if self.conversation_id:
            conversation = self.db.get_conversation(self.conversation_id)
            context = conversation["context"]        
        else:
            context = None

        compiler = ContactImagePromptCompiler(contact_data, user_data, context, self.image_type, self.show_assistant, self.show_user)
        positive_prompt, negative_prompt = compiler.build()

        models = {
            "default": "DreamShaperXL_Turbo_V2-SFW.safetensors",
            "nsfw-default": "lustifySDXLNSFW_ggwpV7.safetensors"
        }    
        model = models[image_parameters.get("model", "default")]        

        # generate profile image
        image_request = ImageRequest(
            positive_prompt = positive_prompt,
            negative_prompt = negative_prompt,
            seed = image_parameters.get("seed", 1337),
            width = self.width,
            height = self.height,
            steps = image_parameters.get("steps", 40.0),
            cfg = image_parameters.get("cfg", 9.0),
            model = model,
            output = ""
        )

        image_gen_hash = Utils.hash_image_request(image_request)
        self.output_file = f"{image_gen_hash}.png"
        self.db.add_contact_image(self.contact_id, self.output_file, self.store_image_as)
        image_request.output = self.output_file

        # skip generation if it already exists
        downloaded_file = Path(f"/hub/images/{self.output_file}")
        if not downloaded_file.exists():
            image_job = ImageJob(image_request, self.infrastructure)
            self.create_and_add(image_job)
            self.wait_for([image_job])

        self.response = image_job.result()
        if not self.response:
            logger.error("failed to generate assistant image")

    def result(self) -> Dict[str, Any]:
        return self.response