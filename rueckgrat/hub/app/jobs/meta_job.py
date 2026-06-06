import json
from .job_queue import Job
from .classification_job import ClassificationJob
from .chat_job import ChatJob
from .assistant_image_job import AssistantImageJob
from .requested_image_job import RequestedImageJob
from typing import Dict, Any

from app.common import Logger, ChatRequest, Utils
logger = Logger(__name__).get_logger()

class MetaJob(Job):
    def __init__(self, user_id: int, request: ChatRequest, db, infrastructure, skills):
        super().__init__()
        self.user_id = user_id
        self.request = request
        self.db = db
        self.infrastructure = infrastructure     
        self.skills = skills

    def _handle_take_photo(self, take_photo, message_id):
        if not "subject" in take_photo:
            logger.error("invalid take_photo")
            return None
        
        subject = take_photo["subject"]
        img_ai = subject in ("self", "both")
        img_usr = subject in ("user", "both")

        if not img_ai and not img_usr:
            logger.error("invalid take_photo")
            return None

        logger.debug(f"taking picture of \"{subject}\" ...")

        width = 720
        height = 1280
        if img_ai and img_usr:
            width = 1280
            height = 720

        assistant_image_job = AssistantImageJob(
            user_id = self.user_id,
            contact_id = self.request.contact_id,
            conversation_id = self.request.conversation_id, 
            db = self.db, 
            infrastructure = self.infrastructure,
            show_assistant = img_ai,
            show_user = img_usr,
            width = width,
            height = height
        )
        self.create_and_add(assistant_image_job)
        self.wait_for([assistant_image_job])
        image_job_result = assistant_image_job.result()

        image = image_job_result["image"]
        image_filename = image["filename"]
        image_url = f"images/{image_filename}"

        self.db.add_attachment(message_id, image_filename, image_url, "image/png", 0)

        return image

    def _handle_image_gen(self, generate_image, message_id, contact_id):
        if not "positive_prompt" in generate_image:
            logger.error("invalid generate_image")
            return None
        
        positive_prompt = generate_image["positive_prompt"]

        logger.debug("generate image ...")
        image_job = RequestedImageJob(positive_prompt, contact_id, self.db, self.infrastructure)
        self.create_and_add(image_job)
        self.wait_for([image_job])
        image_job_result = image_job.result()

        image = image_job_result["image"]
        image_filename = image["filename"]
        image_url = f"images/{image_filename}"

        self.db.add_attachment(message_id, image_filename, image_url, "image/png", 0)

        logger.debug("image generated")

        return image
            
    def execute(self) -> None:
        self.response = {}

        logger.debug("recieved message request")
        self.db.add_message(self.request.conversation_id, self.request.role, self.request.content, self.request.name)

        try:
            logger.debug("execute meta job")
            contact = self.db.get_contact_by_id(self.request.contact_id)
            contact_name = Utils.get_nested_value(contact, ["identity", "name"])

            logger.debug("gen assistant response ...")
            chat_job = ChatJob(self.request, self.db, self.infrastructure, self.skills)
            self.create_and_add(chat_job)
            self.wait_for([chat_job])
            chat_response = chat_job.result()

            #dumped = json.dumps(chat_response, indent=4).replace('\\n', '\n')
            #logger.debug(f"chat response:\n{dumped}")

            message_id = self.db.add_message(self.request.conversation_id, "assistant", chat_response["content"], contact_name)
            self.response["chat"] = chat_response
            tool_calls = chat_response["tool_calls"]

            logger.debug(f"tool_calls: \n{tool_calls}")

            for tool in tool_calls:
                if tool["tool"] == "take_photo":
                    image = self._handle_take_photo(tool, message_id)
                    self.response["take_photo"] = image

                if tool["tool"] == "generate_image":
                    image = self._handle_image_gen(tool, message_id, self.request.contact_id)
                    self.response["generate_image"] = image
            
            logger.debug("assistant response generated")

            logger.debug("... done")

        except Exception as e:
            logger.error(f"failed to execute MetaJob {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True