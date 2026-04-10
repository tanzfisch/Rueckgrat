from .job_queue import Job
from .classification_job import ClassificationJob
from .chat_job import ChatJob
from .assistant_image_job import AssistantImageJob
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

            logger.debug("classify...")
            classify = ClassificationJob(self.request.content)
            self.create_and_add(classify)
            self.wait_for([classify])
            classifications = classify.result()["classifications"]
            logger.debug(f"classifications found: {classifications}")

            # if "conversation" in classifications:
            logger.debug("gen assistant response...")
            chat_job = ChatJob(self.request, self.db, self.infrastructure)
            self.create_and_add(chat_job)
            self.wait_for([chat_job])
            self.response["chat"] = chat_job.result()

            logger.debug("store message response")
            contact = self.db.get_contact_by_id(self.request.contact_id)
            message_id = self.db.add_message(self.request.conversation_id, chat_job.result()["role"], chat_job.result()["content"], contact["name"])

            if "assistant_image_generation_request" in classifications:
                logger.debug("gen assistant image...")
                assistant_image_job = AssistantImageJob(self.request, self.db, self.infrastructure)
                self.create_and_add(assistant_image_job)
                self.wait_for([assistant_image_job])
                image = assistant_image_job.result()
                image_filename = image["filename"]
                image_size = image["file_size"]
                image_url = f"images/{image_filename}"
                self.db.add_attachment(message_id, image_filename, image_url, "image/png", image_size)
                self.response["assistant_image"] = image_filename                    

            logger.debug("... done")

        except Exception as e:
            logger.error(f"failed to execute MetaJob {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True