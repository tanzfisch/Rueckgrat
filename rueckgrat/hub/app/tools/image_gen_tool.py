from typing import Dict,  Any
from .image_tool import ImageTool
from app.tasks.requested_image_task import RequestedImageTask

from app.common import get_logger
logger = get_logger()

class ImageGenTool(ImageTool):
    description = "generates a picture from a description when the user asks for an image"
    question = [
        "Does the user ask you to draw, paint or illustrate something?",
        "Does the user want a picture or drawing made?",
        "Does the user want a picture, drawing, logo or wallpaper made?"
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str: 
        return "generate_image"

    def create_image_job(self):
        """the RequestedImageTask for this tool call (not started), None if the call is invalid.
        execute() attaches its planned file name before the image is generated"""
        if not "positive_prompt" in self.tool_call:
            logger.error("invalid generate_image")
            return None
        return RequestedImageTask(self.tool_call["positive_prompt"], self.contact_id, self.db, self.infrastructure,
                                 conversation_id=self.conversation_id)

    def execute(self) -> None:
        image_task = self.create_image_job()
        if not image_task:
            return None
        self.attach_planned_image(image_task)

        logger.debug("generating image ...")
        self.add_sub_task(image_task)
        self.wait_for([image_task])
        image = (image_task.get_result() or {}).get("image")

        if not image:
            output_file = getattr(image_task, "output_file", None)
            if output_file:
                logger.warning(f"generate_image failed, attaching {output_file} for lazy regeneration")
                image = {"filename": output_file, "image_path": f"images/{output_file}"}
            else:
                logger.error("generate_image failed before a file name was planned, no attachment")
                return None

        result = {
            "tool": self.name(),
            "text": "generated image",
            "image": image
        }
        self.held(result, image, "it is attached to your message")

        self.add_result(result)

    def planned_text(self) -> str:
        return "an image is being generated, it gets attached to your message"

    @classmethod
    def prompt(cls) -> str: 
        return """
IMAGE GENERATION:
Use when the user asks you to generate, create, or visualize a picture.

Parameters:
- positive_prompt (string, required): the image description

Example:
{"tool": "generate_image", "positive_prompt": "a red bicycle in a sunny park"}
"""
