from typing import Tuple
from .tool import Tool
from . import prompts
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH

from app.common import get_logger
logger = get_logger()

MAX_FILE_BYTES = 1024 * 1024    # a text file read or changed whole, a bigger one is looked into with commands
READ_LINES = 200                # lines of one read by default
MAX_READ_LINES = 400
MAX_LINE_CHARS = 500            # of one line shown, a minified file has very long ones


class FileTool(Tool):
    """a text file of the contact's sandbox files (SandboxVolume), read or changed without a sandbox container: the
    tools of an agent job's worker loop (Worker). no laya question: only the Worker offers them, a tool setup never
    (ToolRegistry.LOOP_TOOLS). sequential: in a round with bash, in the order of the calls"""
    sequential = True

    def _volume_path(self) -> Tuple[SandboxVolume, str]:
        """the contact's volume and the call's path below MOUNT_PATH (SandboxVolume.resolve: full, or relative to the
        conversation's folder). ValueError when it is missing or outside the files"""
        path = self.tool_call.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path is missing")
        volume = SandboxVolume(self.get_user_id(), self.contact_id)
        return volume, volume.resolve(path, self.get_conversation_id())

    @staticmethod
    def _read(volume: SandboxVolume, path: str) -> bytes:
        """the bytes of the file path, ValueError when it is larger than MAX_FILE_BYTES, FileNotFoundError"""
        _, size, chunks = volume.read_file(path)
        if size > MAX_FILE_BYTES:
            next(chunks, None)      # started and closed: its reader container is removed
            chunks.close()
            raise ValueError("too large")
        return b"".join(chunks)

    def _error(self, text: str) -> None:
        self.add_result({"tool": self.name(), "error": text})

    @classmethod
    def prompt(cls) -> str:
        raise NotImplementedError


class ReadFileTool(FileTool):
    """the lines start to start + lines of a text file, numbered"""
    description = prompts.READ_FILE_DESCRIPTION

    @classmethod
    def name(cls) -> str:
        return "read_file"

    @classmethod
    def prompt(cls) -> str:
        return prompts.READ_FILE_PROMPT.format(files=MOUNT_PATH)

    def execute(self) -> None:
        try:
            volume, path = self._volume_path()
            start = max(1, int(self.tool_call.get("start") or 1))
            count = min(MAX_READ_LINES, max(1, int(self.tool_call.get("lines") or READ_LINES)))
        except (ValueError, TypeError) as e:
            self._error(str(e))
            return
        full = f"{MOUNT_PATH}/{path}"
        try:
            data = self._read(volume, path)
        except FileNotFoundError:
            self._error(f"{full} is not there")
            return
        except ValueError:
            self._error(prompts.READ_FILE_TOO_LARGE_PART.format(path=full, limit=MAX_FILE_BYTES // (1024 * 1024)))
            return
        except Exception as e:
            logger.error(f"read_file {full} failed {repr(e)}")
            self._error(f"{full} could not be read: {e}")
            return
        if b"\0" in data:
            self._error(prompts.READ_FILE_BINARY_PART.format(path=full))
            return
        lines = data.decode("utf-8", errors="replace").splitlines()
        if not lines:
            self.add_result({"tool": self.name(), "text": prompts.READ_FILE_EMPTY_PART.format(path=full)})
            return
        first = min(start, len(lines))
        shown = lines[first - 1:first - 1 + count]
        numbered = "\n".join(f"{number:>5}| {line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + ' [...]'}"
                             for number, line in enumerate(shown, first))
        self.add_result({"tool": self.name(), "text": prompts.READ_FILE_PART.format(
            path=full, first=first, last=first + len(shown) - 1, total=len(lines), lines=numbered)})


class EditFileTool(FileTool):
    """replaces the one place of old in a text file by new, or (no old) writes new as the whole file. the file belongs
    to the sandbox user (SandboxVolume.write_file), its full path goes into the result's "saved" """
    description = prompts.EDIT_FILE_DESCRIPTION

    @classmethod
    def name(cls) -> str:
        return "edit_file"

    @classmethod
    def prompt(cls) -> str:
        return prompts.EDIT_FILE_PROMPT.format(files=MOUNT_PATH)

    def execute(self) -> None:
        old, new = self.tool_call.get("old"), self.tool_call.get("new")
        try:
            volume, path = self._volume_path()
            if not isinstance(new, str):
                raise ValueError("new is missing: the new text, \"\" to delete the old one")
            if old is not None and not isinstance(old, str):
                raise ValueError("old must be text")
        except ValueError as e:
            self._error(str(e))
            return
        full = f"{MOUNT_PATH}/{path}"
        try:
            if old:
                text = self._read(volume, path).decode("utf-8")
                count = text.count(old)
                if count != 1:
                    self._error((prompts.EDIT_FILE_MANY_PART if count else prompts.EDIT_FILE_NOT_FOUND_PART).format(path=full, count=count))
                    return
                text = text.replace(old, new)
                volume.write_file(path, text.encode("utf-8"))
                result = prompts.EDIT_FILE_REPLACED_PART.format(path=full, old_lines=old.count("\n") + 1,
                                                                new_lines=new.count("\n") + 1 if new else 0, lines=len(text.splitlines()))
            else:
                volume.write_file(path, new.encode("utf-8"))
                result = prompts.EDIT_FILE_WRITTEN_PART.format(path=full, lines=len(new.splitlines()))
        except FileNotFoundError:
            self._error(prompts.EDIT_FILE_NO_FILE_PART.format(path=full))
            return
        except UnicodeDecodeError:
            self._error(prompts.READ_FILE_BINARY_PART.format(path=full))
            return
        except ValueError:
            self._error(prompts.EDIT_FILE_TOO_LARGE_PART.format(path=full, limit=MAX_FILE_BYTES // (1024 * 1024)))
            return
        except Exception as e:
            logger.error(f"edit_file {full} failed {repr(e)}")
            self._error(f"{full} could not be written: {e}")
            return
        self.add_result({"tool": self.name(), "text": result, "saved": [full]})
