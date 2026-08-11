from typing import Dict,  Any
from .tool import Tool
from app.jobs.assistant_image_job import AssistantImageJob

from app.common import get_logger, MessageQueue
logger = get_logger()

class TakePhotoTool(Tool):
    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str: 
        return "take_photo"

    def execute(self) -> None:
        if not "subject" in self.tool_call:
            logger.error("invalid take_photo")
            return None
        
        subject = self.tool_call["subject"]
        img_ai = subject in ("self", "both")
        img_usr = subject in ("user", "both")

        if not img_ai and not img_usr:
            logger.error("invalid take_photo")
            return None

        logger.debug(f"taking picture of \"{subject}\" ...")
        MessageQueue().send_status_message("taking a picture")

        width = 720
        height = 1280
        if img_ai and img_usr:
            width = 1280
            height = 720

        assistant_image_job = AssistantImageJob(
            user_id = self.user_id,
            contact_id = self.contact_id,
            conversation_id = self.conversation_id, 
            db = self.db, 
            infrastructure = self.infrastructure,
            show_assistant = img_ai,
            show_user = img_usr,
            width = width,
            height = height
        )

        self.add_sub_job(assistant_image_job)
        self.wait_for([assistant_image_job])
        image_job_result = assistant_image_job.result()

        image = image_job_result["image"]
        self.response["take_photo"] = image        

    @classmethod
    def prompt(cls) -> str: 
        return """
TAKE PHOTO:

You can take a picture (photograph, selfie, snap shot) of yourself, the user or both together in the current situation by including following json recipe in your response

{
  "tool": "take_photo",
  "subject": "self" | "user" | "both"
}
"""
