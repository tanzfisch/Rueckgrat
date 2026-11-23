import posixpath
from typing import Dict, Any, List, Tuple
from .tool import Tool
from . import prompts
from app.utils.text_files import attach_message_file, sanitize_relative_path, MAX_ATTACH_BYTES
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH

MAX_ATTACH_FILES = 50   # files one call offers, a folder with more is cut there

from app.common import get_logger, MessageQueue
logger = get_logger()


class ShareFileTool(Tool):
    """offers files of the contact's sandbox files (SandboxVolume) to the user: attached to the assistant message as
    download cards, writes nothing. a path is a file or a folder (all its files, .git, caches and packages left out),
    relative to the conversation's current bash folder or absolute under MOUNT_PATH. without a message (an agent job's
    worker, a companion pass) the files are held in the result's "attachments", attached to the message the job posts
    (attach_held).
    offering is shared with the tools that write a file (WriteFileTool, TextToSpeechTool, JoinFilesTool: _offered, _kept,
    attach_held, merge), and so is writing it without replacing a file unless the call says overwrite (_write)"""
    description = prompts.SHARE_FILE_DESCRIPTION
    sequential = True           # runs after the round's bash calls that make the files
    offered_with = ("bash",)   # no laya question: offered (optional) whenever a tool that makes files is
    # the largest file it attaches. every file of a shared folder is read into memory at once, so not more by default
    max_attach_bytes = MAX_ATTACH_BYTES

    @classmethod
    def name(cls) -> str:
        return "share_file"

    def runs_detached(self) -> bool:
        """it reads the sandbox files, the reply has to know what was offered and what not"""
        return False

    def volume(self) -> SandboxVolume:
        return SandboxVolume(self.get_user_id(), self.contact_id)

    def _overwrite(self) -> bool:
        """the call says an existing file at its full path may be replaced (overwrite: true)"""
        return self.tool_call.get("overwrite") in (True, "true", "True")

    def _check_free(self, stored: str, full: bool) -> None:
        """ValueError when a full path (full) names something that is there already and the call does not say overwrite.
        a plain name is kept under its content's hash (SandboxVolume.document_path, tts_path): never another file"""
        if full and not self._overwrite() and self.volume().has_file(stored):
            raise ValueError(prompts.FILE_EXISTS_PART.format(path=f"{MOUNT_PATH}/{stored}"))

    def _write(self, stored: str, data: bytes, full: bool) -> None:
        """writes the file the call made (_check_free first)"""
        self._check_free(stored, full)
        self.volume().write_file(stored, data)

    def _kept(self, real: str, stored: str, data: bytes, lead: str) -> Dict[str, Any]:
        """the result of a file written to stored, its text after lead (what was made): offered like _offered, or when
        it is larger than max_attach_bytes kept in the files only, the user downloads it in the files browser"""
        saved = [f"{MOUNT_PATH}/{stored}"]
        if len(data) > self.max_attach_bytes:
            return {"tool": self.name(), "saved": saved, "text": f"{lead} " + prompts.FILE_TOO_LARGE_PART.format(
                path=saved[0], size=f"{len(data) / (1024 * 1024):.0f}", limit=self.max_attach_bytes // (1024 * 1024))}
        result = self._offered([(real, stored, data)], [])
        if result.get("file_names"):
            result.update(text=f"{lead} {self._text(result['file_names'], saved)}".strip(), saved=saved)
        return result

    def execute(self) -> None:
        paths = self.tool_call.get("path")
        paths = [paths] if isinstance(paths, str) else [path for path in paths or [] if isinstance(path, str)]
        MessageQueue().send_status_message("sharing files")
        volume = self.volume()
        found: List[Tuple[str, str, bytes | None]] = []
        problems: List[str] = []
        for path in paths:
            before = len(found)
            try:
                real = volume.resolve(path, self.get_conversation_id())
                parent = posixpath.dirname(real)
                # the name the user sees: below the shared path's folder (a file alone, a folder with its own name)
                found += [(posixpath.relpath(name, parent) if parent else name, name, data)
                          for name, _, data in volume.files(real, max_bytes=self.max_attach_bytes)]
            except ValueError:
                problems.append(f"{path} is not a path in your files")
            except FileNotFoundError:
                problems.append(f"{path} is not in your files")
            except Exception as e:
                logger.error(f"failed to share {path} {repr(e)}")
                problems.append(f"{path} could not be shared - {type(e).__name__}")
            else:
                if len(found) == before:
                    problems.append(f"{path} has no files")
        if not paths:
            problems.append("no path given")
        self.add_result(self._offered(found, problems))

    def _offered(self, files: List[Tuple[str, str, bytes | None]], problems: List[str]) -> Dict[str, Any]:
        """the result of offering files [(the name the user sees, its path in the sandbox files, its bytes, None when
        larger than max_attach_bytes)]: attached to the message, or held without one. problems: what could not be
        offered before, named in the text with what fails here"""
        file_names: List[str] = []
        held: List[Dict[str, Any]] = []
        problems = list(problems)
        for name, path, data in files:
            if len(file_names) >= MAX_ATTACH_FILES:
                problems.append(f"only the first {MAX_ATTACH_FILES} files were attached")
                break
            if data is None:
                problems.append(f"{name} is larger than {self.max_attach_bytes // (1024 * 1024)} MB")
            elif not sanitize_relative_path(name):
                problems.append(f"{name} can't be attached (hidden file or folder)")
            elif self.message_id is None:
                # only the path: the held list goes into the job's json result, attach_held reads the file
                held.append({"tool": self.name(), "name": name, "path": path, "sandbox": True})
                file_names.append(name)
            else:
                try:
                    file_names.append(self._attach(self.db, self.get_user_id(), self.get_conversation_id(), self.message_id,
                                                   name, data, True)["file_name"])
                except ValueError as e:
                    problems.append(str(e))
        texts = ([self._text(file_names)] if file_names else []) + \
                ([prompts.WRITE_FILE_NOT_ATTACHED_PART.format(problems="; ".join(dict.fromkeys(problems)))] if problems else [])
        result = {"tool": self.name(), "text": " ".join(texts)}
        if file_names:
            result["file_names"] = file_names
        if held:
            result["attachments"] = held
        return result

    @classmethod
    def attach_held(cls, db, user_id: int, conversation_id: int, message_id: int, held: Dict[str, Any], push: bool) -> None:
        """held: {"tool", "name" (the name the user sees), "path" (in the sandbox files, the name when missing),
        "sandbox": True}, the file read now (as it is when the report is made). ValueError when it is gone or too large"""
        path = held.get("path") or held["name"]
        content = next((data for name, _, data in SandboxVolume.of_conversation(db, user_id, conversation_id).files(
            path, max_bytes=cls.max_attach_bytes) if name == path), None)
        if content is None:
            raise ValueError(f"{path} is not a file or larger than {cls.max_attach_bytes // (1024 * 1024)} MB")
        cls._attach(db, user_id, conversation_id, message_id, held["name"], content, push)

    @classmethod
    def _attach(cls, db, user_id: int, conversation_id: int, message_id: int, name: str, content: str | bytes, push: bool) -> Dict[str, Any]:
        """writes the file for the message and pushes it to the chat (push: the user has an open /ws). returns the payload,
        ValueError for an invalid file"""
        payload = attach_message_file(db, user_id, conversation_id, message_id, name, content, max_bytes=cls.max_attach_bytes)
        if push:
            MessageQueue().send_data({"text_files": {
                "conversation_id": conversation_id,
                "message_id": message_id,
                **payload,
            }}, user_id=user_id)
        return payload

    @staticmethod
    def _text(file_names, saved=()) -> str:
        """saved: where write_file kept its files in the sandbox files"""
        return prompts.WRITE_FILE_ATTACHED_PART.format(file_names=', '.join(file_names)) + \
            (" " + prompts.WRITE_FILE_SAVED_PART.format(paths=", ".join(saved)) if saved else "")

    @classmethod
    def merge(cls, known: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """one line for all files of a message. a failed file keeps its own text. a file attached again (a worker's
        later turn) is named once, its later held entry kept"""
        if not known.get("file_names") or not result.get("file_names"):
            return super().merge(known, result)
        file_names = list(dict.fromkeys(known["file_names"] + result["file_names"]))
        saved = list(dict.fromkeys(known.get("saved", []) + result.get("saved", [])))
        merged = {**known, "text": cls._text(file_names, saved), "file_names": file_names, **({"saved": saved} if saved else {})}
        if "attachments" in known or "attachments" in result:
            held = {}
            for item in known.get("attachments", []) + result.get("attachments", []):
                held.pop(item.get("name"), None)
                held[item.get("name")] = item
            merged["attachments"] = list(held.values())
        return merged

    @classmethod
    def prompt(cls) -> str:
        return prompts.SHARE_FILE_PROMPT.format(files=MOUNT_PATH)
