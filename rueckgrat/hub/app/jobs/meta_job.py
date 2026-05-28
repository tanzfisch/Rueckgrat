import random
from .job_queue import Job
from .classification_job import ClassificationJob
from .chat_job import ChatJob
from .assistant_image_job import AssistantImageJob
from .requested_image_job import RequestedImageJob
from typing import Dict, Any

from app.common import Logger, ChatRequest, Utils
logger = Logger(__name__).get_logger()

class MetaJob(Job):
    def __init__(self, user_id: int, request: ChatRequest, db, infrastructure):
        super().__init__()
        self.user_id = user_id
        self.request = request
        self.db = db
        self.infrastructure = infrastructure     

    def cleanup_content(self, content: str) -> str:
        content = content.replace("<IMG_AI>", "").strip()
        content = content.replace("IMG_AI", "").strip()
        content = content.replace("<IMG_USR>", "").strip()
        content = content.replace("IMG_USR", "").strip()
        content = content.replace("<IMG_GRP>", "").strip()
        content = content.replace("IMG_GRP", "").strip()
        return content
    
    def execute(self) -> None:
        self.response = {}

        logger.debug("recieved message request")
        self.db.add_message(self.request.conversation_id, self.request.role, self.request.content, self.request.name)

        try:
            logger.debug("execute meta job")
            img_ai = False
            img_usr = False

            logger.debug("classify...")
            classify = ClassificationJob(self.request.content)
            self.create_and_add(classify)
            self.wait_for([classify])
            classifications = classify.result()["classifications"]
            logger.debug(f"classifications found: {classifications}")

            contact = self.db.get_contact_by_id(self.request.contact_id)
            contact_name = Utils.get_nested_value(contact, ["name"])

            if "image_generation_request" in classifications:
                logger.debug("generate image...")
                image_job = RequestedImageJob(self.request, self.db, self.infrastructure)
                self.create_and_add(image_job)
                self.wait_for([image_job])
                image_job_result = image_job.result()

                image = image_job_result["image"]
                image_filename = image["filename"]
                image_size = image["file_size"]
                image_url = f"images/{image_filename}"

                # updat db
                message_id = self.db.add_message(self.request.conversation_id, "assistant", "", contact_name)        
                self.db.add_attachment(message_id, image_filename, image_url, "image/png", image_size)

                # notify frontend # TODO maybe frontend should only be notified to pull the latest from the DB to prevent double handling
                self.response["chat"] = { "role": "assistant","content": "" }
                self.response["image"] = image

                logger.debug("image generated")

            if "conversation" in classifications:
                logger.debug("gen assistant response...")                
                chat_job = ChatJob(self.request, self.db, self.infrastructure)
                self.create_and_add(chat_job)
                self.wait_for([chat_job])

                content = chat_job.result()["content"]

                if not "image_generation_request" in classifications: # one image is enough
                    if "IMG_AI" in content:
                        img_ai = True
                    elif "IMG_USR" in content:
                        # TODO this currently does not work well
                        img_ai = True
                        #img_usr = True
                    elif "IMG_GRP" in content:
                        # TODO this currently does not work well
                        img_ai = True
                        #img_usr = True

                content = self.cleanup_content(content)

                # update db
                if "image_generation_request" in classifications:
                    self.db.update_message(message_id, chat_job.result()["role"], content, contact_name)
                else:
                    message_id = self.db.add_message(self.request.conversation_id, chat_job.result()["role"], content, contact_name)

                # notify frontend
                chat_job.result()["content"] = content
                self.response["chat"] = chat_job.result()
                
                logger.debug("assistant response generated")

            if img_ai or img_usr:
                logger.debug("generate mood image...")

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

                # update db
                self.db.add_attachment(message_id, image_filename, image_url, "image/png", 0)

                # notify frontend
                self.response["image"] = image

                logger.debug("mood image generated")

            logger.debug("... done")

        except Exception as e:
            logger.error(f"failed to execute MetaJob {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True