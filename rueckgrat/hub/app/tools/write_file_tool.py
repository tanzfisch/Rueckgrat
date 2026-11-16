from typing import Dict, Any
from . import prompts
from .share_file_tool import ShareFileTool
from app.utils.text_files import check_file
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH, DOCUMENTS

from app.common import get_logger, MessageQueue
logger = get_logger()


class WriteFileTool(ShareFileTool):
    """writes the one text file of the call (path, content) into the contact's sandbox files, only as
    DOCUMENTS/<hash>/<path> (SandboxVolume.document_path: a write never overwrites another file), and offers it to the
    user like share_file does (one file as itself, the files of one answer also as a zip in the chat)"""
    description = prompts.WRITE_FILE_DESCRIPTION
    sequential = False
    offered_with = ()
    # laya, not a prompt tool: a file is only made when the message asks for one, not on every turn
    thresholds = (0.45, 0.5)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user ask to save, export or download something as a text, CSV, markdown or Word file?",
    ]

    @classmethod
    def name(cls) -> str:
        return "write_file"

    def runs_detached(self) -> bool:
        """the file is checked before (planned_result), writing it runs in the background"""
        return True

    def _checked(self) -> tuple[str, bytes, str]:
        """(the real relative path, the bytes, where it is kept in the sandbox files) of the call's file, ValueError if
        it is not a valid one (check_file)"""
        real, data = check_file(self.tool_call.get("path"), self.tool_call.get("content"))
        return real, data, SandboxVolume.document_path(real, data)

    def execute(self) -> None:
        """writes the file into the sandbox files and attaches it to the assistant message. without a message (an
        agent job's worker) it is held in the result's "attachments", the job attaches it to its report (attach_held)"""
        path = self.tool_call.get("path")
        MessageQueue().send_status_message("writing files")
        try:
            real, data, stored = self._checked()
            self.volume().write_file(stored, data)
        except Exception as e:
            logger.error(f"failed to write file {path} {repr(e)}")
            self.add_result({"tool": self.name(), "text": f"failed to write {path} - {e}"})
            return
        result = self._offered([(real, stored, data)], [])
        if result.get("file_names"):
            result.update(text=self._text(result["file_names"], [f"{MOUNT_PATH}/{stored}"]), saved=[f"{MOUNT_PATH}/{stored}"])
        self.add_result(result)

    def planned_result(self) -> Dict[str, Any]:
        """the file is checked now, writing it runs detached"""
        path = self.tool_call.get("path")
        try:
            real, _, stored = self._checked()
        except Exception as e:
            return {self.name(): {"tool": self.name(), "text": f"failed to write {path} - {e}"}}
        saved = [f"{MOUNT_PATH}/{stored}"]
        return {self.name(): {"tool": self.name(), "text": self._text([real], saved), "file_names": [real], "saved": saved}}

    @classmethod
    def prompt(cls) -> str:
        return prompts.WRITE_FILE_PROMPT.format(documents=f"{MOUNT_PATH}/{DOCUMENTS}")
