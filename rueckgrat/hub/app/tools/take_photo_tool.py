from typing import Dict,  Any, Optional
from .tool import Tool, ToolCategory
from app.jobs.assistant_image_job import AssistantImageJob

from app.common import get_logger, MessageQueue, Utils
logger = get_logger()

class TakePhotoTool(Tool):
    category = ToolCategory.MEDIA
    description = "takes a photo of yourself, the user or both in the current situation"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str: 
        return "take_photo"

    def create_image_job(self) -> Optional[AssistantImageJob]:
        """the AssistantImageJob for this tool call (not started), None if the call is invalid.
        execute() attaches its planned file name before the photo is taken"""
        if not "subject" in self.tool_call:
            logger.error("invalid take_photo")
            return None
        
        subject = self.tool_call["subject"]
        img_ai = subject in ("self", "both")
        img_usr = subject in ("user", "both")

        if not img_ai and not img_usr:
            logger.error("invalid take_photo")
            return None

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
        return assistant_image_job

    def attach_planned_image(self, image_job) -> None:
        """attaches the image file of image_job (not started yet) to the message in tool_call["message_id"].
        the file name is the hash of the request the job will build (output ""), so it is known before
        the image exists. the image job itself knows nothing about messages"""
        message_id = self.tool_call.get("message_id")
        if not message_id or message_id < 0:
            logger.warning(f"{self.name()}: no message id, image not attached")
            return
        try:
            image_filename = f"{Utils.hash_image_request(image_job.build_request())}.png"
            self.db.add_attachment(message_id, image_filename, f"images/{image_filename}", "image/png", 0)
            logger.debug(f"{self.name()}: attached planned file {image_filename} to message {message_id}")
            # tell the client now, the image itself takes minutes. it shows the placeholder and starts the download
            MessageQueue().send_data({
                "attachment": {
                    "conversation_id": self.conversation_id,
                    "message_id": message_id,
                    "filename": image_filename
                }
            })
        except Exception as e:
            logger.error(f"{self.name()}: failed to attach the planned image {repr(e)}")

    def execute(self) -> None:
        assistant_image_job = self.create_image_job()
        if not assistant_image_job:
            return None
        self.attach_planned_image(assistant_image_job)

        logger.debug(f"taking picture of \"{self.tool_call['subject']}\" ...")
        MessageQueue().send_status_message("taking a picture")

        self.add_sub_job(assistant_image_job)
        self.wait_for([assistant_image_job])
        image = (assistant_image_job.result() or {}).get("image")

        if not image:
            # generation failed, but the file name and its parameters (images table) are already stored.
            # attach the planned file anyway, the hub's ImageStore generates it again when it gets downloaded
            output_file = getattr(assistant_image_job, "output_file", None)
            if output_file:
                logger.warning(f"take_photo failed, attaching {output_file} for lazy regeneration")
                image = {"filename": output_file, "image_path": f"images/{output_file}"}
            else:
                logger.error("take_photo failed before a file name was planned, no attachment")
                return None

        self.response["take_photo"] = image        

    @classmethod
    def prompt(cls) -> str: 
        return """
TAKE PHOTO:
Use when the user wants a photo of you, themselves, or both in the current situation.

Parameters:
- subject (string, required): "self", "user", or "both"

Example:
{"tool": "take_photo", "subject": "both"}
"""
