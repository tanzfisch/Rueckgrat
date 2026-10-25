from typing import Dict,  Any
from .tool import Tool, ToolCategory
from app.jobs.requested_image_job import RequestedImageJob

from app.common import get_logger, MessageQueue, Utils
logger = get_logger()

class ImageGenTool(Tool):
    category = ToolCategory.MEDIA
    description = "generates a picture from a description when the user asks for an image"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str: 
        return "generate_image"

    def create_image_job(self):
        """the RequestedImageJob for this tool call (not started), None if the call is invalid.
        execute() attaches its planned file name before the image is generated"""
        if not "positive_prompt" in self.tool_call:
            logger.error("invalid generate_image")
            return None
        return RequestedImageJob(self.tool_call["positive_prompt"], self.contact_id, self.db, self.infrastructure,
                                 conversation_id=self.conversation_id)

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
        image_job = self.create_image_job()
        if not image_job:
            return None
        self.attach_planned_image(image_job)

        logger.debug("generating image ...")
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
Use when the user asks you to generate, create, or visualize a picture.

Parameters:
- positive_prompt (string, required): the image description

Example:
{"tool": "generate_image", "positive_prompt": "a red bicycle in a sunny park"}
"""
