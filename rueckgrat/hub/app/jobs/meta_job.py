from .job_queue import Job
from .classification_job import ClassificationJob
from .chat_job import ChatJob
from .assistant_image_job import AssistantImageJob
from .requested_image_job import RequestedImageJob
from typing import Dict, Any

from app.common import Logger, ChatRequest
logger = Logger(__name__).get_logger()

class MetaJob(Job):
    def __init__(self, request: ChatRequest, db, infrastructure):
        super().__init__()
        self.request = request
        self.db = db
        self.infrastructure = infrastructure     

    def execute(self) -> None:
        self.response = {}

        logger.debug("recieved message request")
        self.db.add_message(self.request.conversation_id, self.request.role, self.request.content, self.request.name)

        try:
            logger.debug("execute meta job")
            mood_gen = False
            group_gen = False

            logger.debug("classify...")
            classify = ClassificationJob(self.request.content)
            self.create_and_add(classify)
            self.wait_for([classify])
            classifications = classify.result()["classifications"]
            logger.debug(f"classifications found: {classifications}")

            contact = self.db.get_contact_by_id(self.request.contact_id)

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
                message_id = self.db.add_message(self.request.conversation_id, "assistant", "", contact["name"])        
                self.db.add_attachment(message_id, image_filename, image_url, "image/png", image_size)

                # notify frontend
                self.response["chat"] = { "role": "assistant","content": "" }
                self.response["image"] = image

                logger.debug("image generated")

            if "conversation" in classifications:
                logger.debug("gen assistant response...")                
                chat_job = ChatJob(self.request, self.db, self.infrastructure)
                self.create_and_add(chat_job)
                self.wait_for([chat_job])

                content = chat_job.result()["content"]
                if "MOOD_GEN" in content:
                    content = content.replace("MOOD_GEN", "").strip()
                    if not "image_generation_request" in classifications: # one image is enough
                        mood_gen = True

                if "GROUP_GEN" in content:
                    content = content.replace("GROUP_GEN", "").strip()
                    if not "image_generation_request" in classifications: # one image is enough
                        group_gen = True


                chat_job.result()["content"] = content

                # update db
                if "image_generation_request" in classifications:
                    self.db.update_message(message_id, chat_job.result()["role"], content, contact["name"])
                else:
                    message_id = self.db.add_message(self.request.conversation_id, chat_job.result()["role"], content, contact["name"])

                # notify frontend
                self.response["chat"] = chat_job.result()
                
                logger.debug("assistant response generated")

            if mood_gen or group_gen:
                logger.debug("generate mood image...")
                assistant_image_job = AssistantImageJob(self.request, self.db, self.infrastructure, mood_gen)
                self.create_and_add(assistant_image_job)
                self.wait_for([assistant_image_job])
                image_job_result = assistant_image_job.result()

                image = image_job_result["image"]
                image_filename = image["filename"]
                image_size = image["file_size"]
                image_url = f"images/{image_filename}"

                # update db
                self.db.add_attachment(message_id, image_filename, image_url, "image/png", image_size)

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