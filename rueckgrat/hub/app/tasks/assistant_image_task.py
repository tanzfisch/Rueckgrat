from .task_queue import Task
from pathlib import Path
from .image_task import ImageTask, ImageRequest
from ..utils.contact_image_prompt_compiler import ContactImagePromptCompiler, ImageType
from typing import Dict, Any

from app.common import get_logger, Utils
logger = get_logger()

class AssistantImageTask(Task):
    def __init__(self, user_id: int, contact_id: int, db, infrastructure, width: int = 720, height: int = 1280, conversation_id: int = None, show_assistant: bool = True, show_user: bool = False, image_type: ImageType = ImageType.FullBody, store_image_as: str = "conversation_images"):
        super().__init__()
        self.user_id = user_id
        self.contact_id = contact_id
        self.conversation_id = conversation_id
        self.db = db
        self.infrastructure = infrastructure
        self.response = {}
        self.show_assistant = show_assistant
        # TODO one FaceID slot, and only one character is reliable: a 'both' shot is of the assistant only
        self.show_user = show_user and not show_assistant
        self.image_type = image_type
        self.store_image_as = store_image_as
        self.width = width
        self.height = height

    def build_request(self) -> ImageRequest:
        """builds the image request from the db (contact, user, conversation context), output stays "".
        no side effects, so MetaTask can call it too and gets the same request and hash as execute()"""
        contact_data = self.db.get_contact_by_id(self.contact_id)
        user_data = self.db.get_user_data(self.user_id)
        image_parameters = contact_data["profile"]["image_parameters"]

        if self.conversation_id:
            conversation = self.db.get_conversation(self.conversation_id)
            context = conversation["context"]        
        else:
            context = None

        # server side NSFW check: users without NSFW access always get the SFW image model,
        # whatever the contact's profile says (the client can edit that)
        nsfw_allowed = self.db.user_nsfw_allowed(self.user_id)

        reference = self.profile_image_reference()
        compiler = ContactImagePromptCompiler(contact_data, user_data, context, self.image_type, self.show_assistant, self.show_user, not reference)
        positive_prompt, negative_prompt = compiler.build()

        models = {
            "default": "DreamShaperXL_Turbo_V2-SFW",
            "nsfw-default": "lustifyNSFWCheckpoint_zenithV9"
        }    
        model_name = image_parameters.get("model", "default")
        model = model_name if not model_name in models else models[model_name]
        if not nsfw_allowed:
            model = models["default"]

        # generate profile image
        image_request = ImageRequest(
            positive_prompt = positive_prompt,
            negative_prompt = negative_prompt,
            seed = image_parameters.get("seed", 1337),
            width = self.width,
            height = self.height,
            steps = image_parameters.get("steps", 30.0),
            cfg = image_parameters.get("cfg", 4.0),
            model = model,
            output = ""
        )

        if reference:
            image_request.reference_image_key = reference

        return image_request

    def profile_image_reference(self) -> str:
        """FaceID reference file key, or "". not used when generating a contact profile image, and not when
        both people are in the shot (one FaceID slot). the key is only returned if the image file exists,
        same as get_current_profile_image_key (ImageStore.ensure is not called for contact references either:
        an upload cannot be regenerated, a missing file means generate without a face reference)"""
        if self.store_image_as == "profile":
            return ""
        if self.show_assistant and self.show_user:
            return ""
        if self.show_assistant:
            return self.db.get_current_profile_image_key(self.contact_id)
        if self.show_user:
            return self.db.get_current_user_profile_image_key(self.user_id)
        return ""

    def execute(self) -> None:
        image_request = self.build_request()
        image_gen_hash = Utils.hash_image_request(image_request)
        self.output_file = f"{image_gen_hash}.png"
        downloaded_file = Path(f"/hub/images/{self.output_file}")
        # no image generation now (not installed or down): no image, e.g. a new contact has no profile image, nothing
        # is recorded that would point to a file that never comes
        if not downloaded_file.exists() and not self.infrastructure.available("image"):
            logger.info(f"image generation not available, no {self.store_image_as} image for contact {self.contact_id}")
            return
        self.db.add_contact_image(self.contact_id, self.output_file, self.store_image_as)
        image_request.output = self.output_file

        # skip generation if it already exists
        if not downloaded_file.exists():
            image_task = ImageTask(image_request, self.infrastructure, self.db)
            self.add_sub_task(image_task)
            self.wait_for([image_task])
            self.response = image_task.get_result()
        else:
            # same response ImageTask gives for an image that is already there
            self.response = {"image": {"filename": self.output_file, "image_path": f"images/{self.output_file}"}}

    def get_result(self) -> Dict[str, Any]:
        return self.response