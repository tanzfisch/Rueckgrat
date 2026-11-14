from typing import Dict, Any

from .tool import Tool
from app.common import get_logger, MessageQueue, Utils
logger = get_logger()

# base class for other image generation related tools
class ImageTool(Tool):
    """a tool that makes one image (generate_image, take_photo). with a message the planned file is attached before the
    image exists. without one (agent jobs, companions) the file is held in the result's "attachments" and attached by
    attach_held to the message the job posts later"""

    def attach_planned_image(self, image_task) -> None:
        """attaches the image file of image_task (not started yet) to the message in self.message_id (set by ToolRegistry, the assistant message being made).
        the file name is the hash of the request the job will build (output ""), so it is known before
        the image exists. the image job itself knows nothing about messages. no message: nothing, the result holds it"""
        message_id = self.message_id
        if not message_id or message_id < 0:
            logger.debug(f"{self.name()}: no message, the image is held in the result")
            return
        try:
            image_filename = f"{Utils.hash_image_request(image_task.build_request())}.png"
            self._attach_image(self.db, self.user_id, self.conversation_id, message_id, image_filename, True)
        except Exception as e:
            logger.error(f"{self.name()}: failed to attach the planned image {repr(e)}")

    def held(self, result: Dict[str, Any], image: Dict[str, Any], note: str) -> Dict[str, Any]:
        """result with the image held when there is no message: its "attachments" and note added to its text"""
        if self.message_id is None:
            result["text"] = f"{result['text']}, {note}"
            result["attachments"] = [{"tool": self.name(), "name": image["filename"]}]
        return result

    @classmethod
    def attach_held(cls, db, user_id: int, conversation_id: int, message_id: int, held: Dict[str, Any], push: bool) -> None:
        """held: {"tool", "name" (the image's file name)}"""
        cls._attach_image(db, user_id, conversation_id, message_id, held["name"], push)

    @staticmethod
    def _attach_image(db, user_id: int, conversation_id: int, message_id: int, image_filename: str, push: bool) -> None:
        """the image file (it may not exist yet) as an attachment of the message. push: tell the client now (the user has
        an open /ws), the image itself takes minutes. it shows the placeholder and starts the download"""
        db.add_attachment(message_id, image_filename, f"images/{image_filename}", "image/png", 0)
        logger.debug(f"attached image {image_filename} to message {message_id}")
        if push:
            MessageQueue().send_data({
                "attachment": {
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "filename": image_filename
                }
            }, user_id=user_id)
