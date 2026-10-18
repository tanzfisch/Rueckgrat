from typing import Dict,  Any
from .tool import Tool, ToolCategory
from app.jobs.requested_image_job import RequestedImageJob

from app.common import get_logger, MessageQueue
logger = get_logger()

class ImageGenTool(Tool):
    category = ToolCategory.MEDIA
    description = "generates a picture from a description when the user asks for an image"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str: 
        return "generate_image"

    def execute(self) -> None:
        if not "positive_prompt" in self.tool_call:
            logger.error("invalid generate_image")
            return None
        
        positive_prompt = self.tool_call["positive_prompt"]

        logger.debug("generating image ...")
        MessageQueue().send_status_message(f"generating image")
        image_job = RequestedImageJob(positive_prompt, self.contact_id, self.db, self.infrastructure)
        self.add_sub_job(image_job)
        self.wait_for([image_job])
        image = (image_job.result() or {}).get("image")

        if not image:
            output_file = getattr(image_job, "output_file", None)
            if output_file:
                logger.warning(f"generate_image failed, attaching {output_file} for lazy regeneration")
                image = {"filename": output_file, "image_path": f"images/{output_file}"}
            else:
                logger.error("generate_image failed before a file name was planned, no attachment")
                return None

        self.response["generate_image"] = image

    @classmethod
    def prompt(cls) -> str: 
        return """
IMAGE GENERATION:

When the user asks you to generate/create/visualize/etc a picture, portrait, or image you can generate one by including the following json recipe in your response

{
  "tool": "generate_image",
  "positive_prompt": "the image generation prompt"
}
"""
