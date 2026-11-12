from typing import Dict, Any
from .tool import Tool
from . import prompts
from app.utils.text_files import attach_message_file, check_file

from app.common import get_logger, MessageQueue
logger = get_logger()


class WriteFileTool(Tool):
    description = prompts.WRITE_FILE_DESCRIPTION
    # laya, not a prompt tool: a file is only made when the message asks for one, not on every turn
    question = [
        "Does the user want a website or more than one file created?",
        "Does the user ask to save text or code as a file rather than only show it in the chat?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "write_file"

    def execute(self) -> None:
        """attaches the file of this call to the assistant message. without a message (an agent job's worker) the file
        is checked and held in the result's "attachments", the job attaches it to its report (attach_held)"""
        path = self.tool_call.get("path")
        content = self.tool_call.get("content")
        MessageQueue().send_status_message("writing files")

        try:
            if self.message_id is None:
                real, _ = check_file(path, content)
                self.add_result({"tool": self.name(), "text": self._text([real]), "file_names": [real],
                                 "attachments": [{"tool": self.name(), "name": real, "content": content}]})
                return
            payload = self._attach(self.db, self.user_id, self.conversation_id, self.message_id, path, content, True)
        except Exception as e:
            logger.error(f"failed to write file {path} {repr(e)}")
            self.add_result({"tool": self.name(), "text": f"failed to write {path} - {e}"})
            return

        file_names = [payload["file_name"]]
        result = {
            "tool": self.name(),
            "text": self._text(file_names),
            "file_names": file_names
        }
        self.add_result(result)

    def planned_result(self) -> Dict[str, Any]:
        """the file is checked now, writing it runs detached"""
        path = self.tool_call.get("path")
        try:
            real, _ = check_file(path, self.tool_call.get("content"))
        except Exception as e:
            return {self.name(): {"tool": self.name(), "text": f"failed to write {path} - {e}"}}
        return {self.name(): {"tool": self.name(), "text": self._text([real]), "file_names": [real]}}

    @classmethod
    def attach_held(cls, db, user_id: int, conversation_id: int, message_id: int, held: Dict[str, Any], push: bool) -> None:
        """held: {"tool", "name" (the path), "content"}"""
        cls._attach(db, user_id, conversation_id, message_id, held["name"], held["content"], push)

    @staticmethod
    def _attach(db, user_id: int, conversation_id: int, message_id: int, path: str, content: str, push: bool) -> Dict[str, Any]:
        """writes the file for the message and pushes it to the chat (push: the user has an open /ws). returns the payload,
        ValueError for an invalid file"""
        payload = attach_message_file(db, user_id, conversation_id, message_id, path, content)
        if push:
            MessageQueue().send_data({"text_files": {
                "conversation_id": conversation_id,
                "message_id": message_id,
                **payload,
            }}, user_id=user_id)
        return payload

    @staticmethod
    def _text(file_names) -> str:
        return prompts.WRITE_FILE_ATTACHED_PART.format(file_names=', '.join(file_names))

    @classmethod
    def merge(cls, known: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """one line for all files of a message. a failed file keeps its own text"""
        if not known.get("file_names") or not result.get("file_names"):
            return super().merge(known, result)
        file_names = known["file_names"] + result["file_names"]
        merged = {**known, "text": cls._text(file_names), "file_names": file_names}
        if "attachments" in known or "attachments" in result:
            merged["attachments"] = known.get("attachments", []) + result.get("attachments", [])
        return merged

    @classmethod
    def prompt(cls) -> str:
        return prompts.WRITE_FILE_PROMPT
