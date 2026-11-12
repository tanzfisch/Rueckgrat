from typing import Dict,  Any, Optional
from .image_tool import ImageTool
from . import prompts
from app.tasks.assistant_image_task import AssistantImageTask

from app.common import get_logger, MessageQueue
logger = get_logger()

class TakePhotoTool(ImageTool):
    description = prompts.TAKE_PHOTO_DESCRIPTION
    question = []

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "take_photo"

    def create_image_job(self) -> Optional[AssistantImageTask]:
        """the AssistantImageTask for this tool call (not started), None if the call is invalid.
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

        width = 768
        height = 1024
        
        if img_ai and img_usr:
            temp = width
            width = height
            height = temp

        assistant_image_task = AssistantImageTask(
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
        return assistant_image_task

    def execute(self) -> None:
        assistant_image_task = self.create_image_job()
        if not assistant_image_task:
            return None
        self.attach_planned_image(assistant_image_task)

        logger.debug(f"taking picture of \"{self.tool_call['subject']}\" ...")
        MessageQueue().send_status_message("taking a picture")

        self.add_sub_task(assistant_image_task)
        self.wait_for([assistant_image_task])
        image = (assistant_image_task.get_result() or {}).get("image")

        if not image:
            # generation failed, but the file name and its parameters (images table) are already stored.
            # attach the planned file anyway, the hub's ImageStore generates it again when it gets downloaded
            output_file = getattr(assistant_image_task, "output_file", None)
            if output_file:
                logger.warning(f"take_photo failed, attaching {output_file} for lazy regeneration")
                image = {"filename": output_file, "image_path": f"images/{output_file}"}
            else:
                logger.error("take_photo failed before a file name was planned, no attachment")
                return None

        result = {
            "tool": self.name(),
            "text": "took a picture",
            "take_photo": image
        }
        self.add_result(self.held(result, image, prompts.IMAGE_ATTACHED_NOTE_PART))

    def planned_text(self) -> str:
        return prompts.TAKE_PHOTO_PLANNED_PART

    @classmethod
    def prompt(cls) -> str: 
        return prompts.TAKE_PHOTO_PROMPT
