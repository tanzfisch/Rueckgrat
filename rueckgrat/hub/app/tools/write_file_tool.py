from typing import Dict, Any
from .tool import Tool, ToolCategory
from app.utils.text_files import sanitize_relative_path, MAX_FILE_BYTES

from app.common import get_logger, MessageQueue
logger = get_logger()


class WriteFileTool(Tool):
    category = ToolCategory.GENERAL
    description = "writes a text file the user can keep, such as a page of a website or a source file or document"
    # laya, not a prompt tool: a file is only made when the message asks for one, not on every turn
    question = [
        "Does the user want a file they can download or keep, such as HTML, CSS, JavaScript or source code?",
        "Does the user want a website or more than one file created?",
        "Does the user ask to save text or code as a file rather than only show it in the chat?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "write_file"

    def execute(self) -> None:
        """keeps the file on the response. the message row does not exist yet, so the bytes are written
        later under that message's id (MetaTask, the same moment image tools learn their message id)"""
        path, content = self.tool_call.get("path"), self.tool_call.get("content")
        real = sanitize_relative_path(path) if isinstance(path, str) else None
        if not real or not isinstance(content, str):
            self._fail(f"invalid file {path!r}")
            return
        if len(content.encode("utf-8")) > MAX_FILE_BYTES or "\0" in content:
            self._fail(f"{real} is too large or not plain text")
            return
        MessageQueue().send_status_message("writing files")
        self.response.setdefault("text_files", []).append({"path": real, "content": content})
        self.response.setdefault("tool_results", []).append({"tool": self.name(), "text": f"queued {real}"})

    def _fail(self, error: str) -> None:
        logger.warning(f"write_file: {error}")
        self.response.setdefault("tool_results", []).append({"tool": self.name(), "error": error})

    @classmethod
    def prompt(cls) -> str:
        return """
WRITE_FILE:
Use when the user wants a file they can keep: a page, a stylesheet, a script, or several of those.
One JSON line per file. A website is several lines, one path each. Put the file text in content.
Paths are relative (index.html, css/style.css). No .. and no absolute path.
Escape quotes and newlines inside content so the line stays valid JSON.

Parameters:
- path (string, required): relative file name
- content (string, required): the whole file

Example:
{"tool": "write_file", "path": "index.html", "content": "<!DOCTYPE html><html><head><link rel=\\"stylesheet\\" href=\\"css/style.css\\"></head><body><h1>Hello</h1></body></html>"}
{"tool": "write_file", "path": "css/style.css", "content": "body { color: #222; }"}
"""
