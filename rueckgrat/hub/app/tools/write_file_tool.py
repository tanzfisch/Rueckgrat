import re
from typing import Dict, Any, List
from .tool import Tool
from . import prompts
from app.utils.text_files import attach_message_file, check_file, sanitize_relative_path, MAX_ATTACH_BYTES
from app.utils.conversation_volume import ConversationVolume, MOUNT_PATH

MAX_ATTACH_FILES = 50   # files one attach call copies, a folder with more is cut there

from app.common import get_logger, MessageQueue
logger = get_logger()


class WriteFileTool(Tool):
    """attaches files to the assistant message as download cards: a tiny file the AI writes into the call (path, content),
    or files of the conversation's sandbox files (attach: paths of files or folders, ConversationVolume.files)"""
    description = prompts.WRITE_FILE_DESCRIPTION
    # laya, not a prompt tool: a file is only made when the message asks for one, not on every turn
    question = [
        "Does the message want to sent files attached to a message?",
        "Does the message ask to download files or a project?",
        "Does the message ask to send, share or hand over files that were made earlier?",
        "Does the message ask to put the finished files or the project into the chat?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "write_file"

    def runs_detached(self) -> bool:
        """an attach call reads the sandbox files, the reply has to know what was attached and what not"""
        return "attach" not in self.tool_call

    def execute(self) -> None:
        """attaches the file of this call to the assistant message. without a message (an agent job's worker) the file
        is checked and held in the result's "attachments", the job attaches it to its report (attach_held)"""
        if "attach" in self.tool_call:
            self._attach_from_files()
            return
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

    def _attach_from_files(self) -> None:
        """attaches (or holds, without a message) the files of the call's "attach" paths from the sandbox files, a folder
        with all its files, .git, caches and packages left out. what could not be attached is named in the text"""
        paths = self.tool_call.get("attach")
        paths = [paths] if isinstance(paths, str) else [path for path in paths or [] if isinstance(path, str)]
        # the bash prompt shows the files at MOUNT_PATH, an absolute path there means the same file
        paths = [path.strip().removeprefix(MOUNT_PATH).lstrip("/") if path.strip().startswith(MOUNT_PATH + "/") or
                 path.strip() == MOUNT_PATH else path for path in paths]
        MessageQueue().send_status_message("attaching files")
        volume = ConversationVolume(self.user_id, self.conversation_id)
        file_names: List[str] = []
        held: List[Dict[str, Any]] = []
        problems: List[str] = []
        for path in paths:
            found = False
            try:
                for name, size, data in volume.files(path, max_bytes=MAX_ATTACH_BYTES):
                    found = True
                    if len(file_names) >= MAX_ATTACH_FILES:
                        problems.append(f"only the first {MAX_ATTACH_FILES} files were attached")
                        break
                    if data is None:
                        problems.append(f"{name} is larger than {MAX_ATTACH_BYTES // (1024 * 1024)} MB")
                    elif not sanitize_relative_path(name):
                        problems.append(f"{name} can't be attached (hidden file or folder)")
                    elif self.message_id is None:
                        # only the path: the held list goes into the job's json result, attach_held reads the file
                        held.append({"tool": self.name(), "name": name, "sandbox": True})
                        file_names.append(name)
                    else:
                        file_names.append(self._attach(self.db, self.user_id, self.conversation_id, self.message_id,
                                                       name, data, True)["file_name"])
            except ValueError:
                problems.append(f"{path} is not a path in your files")
            except FileNotFoundError:
                problems.append(f"{path} is not in your files")
            except Exception as e:
                logger.error(f"failed to attach {path} {repr(e)}")
                problems.append(f"{path} could not be attached - {type(e).__name__}")
            else:
                if not found:
                    problems.append(f"{path} has no files, nothing was written there")
        texts = ([self._text(file_names)] if file_names else []) + \
                ([prompts.WRITE_FILE_NOT_ATTACHED_PART.format(problems="; ".join(dict.fromkeys(problems)))] if problems else [])
        result = {"tool": self.name(), "text": " ".join(texts) or prompts.WRITE_FILE_NOT_ATTACHED_PART.format(problems="no path given")}
        if file_names:
            result["file_names"] = file_names
        if held:
            result["attachments"] = held
        self.add_result(result)

    @classmethod
    def problems(cls, result: Dict[str, Any]) -> List[str]:
        """the files an attach call could not attach (WRITE_FILE_NOT_ATTACHED_PART) or a file that failed"""
        if "error" in result:
            return [f"write_file: {result['error']}"]
        text = result.get("text") or ""
        found = re.findall(r"Not attached: (.*?)\. Tell the user", text, re.S)
        return [f"write_file did not attach: {problem}" for problem in found] + \
               [line for line in text.splitlines() if line.startswith("failed to write ")]

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
        """held: {"tool", "name" (the path), "content" (the str written)} or {"tool", "name", "sandbox": True}, a file of
        the sandbox files read now (as it is when the report is made), ValueError when it is gone or too large"""
        content = held.get("content")
        if held.get("sandbox"):
            content = next((data for name, _, data in ConversationVolume(user_id, conversation_id).files(
                held["name"], max_bytes=MAX_ATTACH_BYTES) if name == held["name"]), None)
            if content is None:
                raise ValueError(f"{held['name']} is not a file or larger than {MAX_ATTACH_BYTES // (1024 * 1024)} MB")
        cls._attach(db, user_id, conversation_id, message_id, held["name"], content, push)

    @staticmethod
    def _attach(db, user_id: int, conversation_id: int, message_id: int, path: str, content: str | bytes, push: bool) -> Dict[str, Any]:
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
        """one line for all files of a message. a failed file keeps its own text. a file attached again (a worker's
        fix round) is named once, its later held entry kept"""
        if not known.get("file_names") or not result.get("file_names"):
            return super().merge(known, result)
        file_names = list(dict.fromkeys(known["file_names"] + result["file_names"]))
        merged = {**known, "text": cls._text(file_names), "file_names": file_names}
        if "attachments" in known or "attachments" in result:
            held = {}
            for item in known.get("attachments", []) + result.get("attachments", []):
                held.pop(item.get("name"), None)
                held[item.get("name")] = item
            merged["attachments"] = list(held.values())
        return merged

    @classmethod
    def prompt(cls) -> str:
        return prompts.WRITE_FILE_PROMPT
