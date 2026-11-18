import posixpath
from typing import List, Tuple
from . import prompts
from .share_file_tool import ShareFileTool
from app.utils.audio_file import AudioFile, AudioFailed, FORMATS, MAX_AUDIO_BYTES
from app.utils.text_files import sanitize_relative_path, is_text
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH, TTS, DOCUMENTS

from app.common import get_logger, MessageQueue
logger = get_logger()

MAX_TEXT_BYTES = 10 * 1024 * 1024   # of one joined text file, it is held in memory


class JoinFilesTool(ShareFileTool):
    """joins files of the contact's sandbox files in their order into one new file and offers it like write_file does
    (ShareFileTool._kept): audio files (what libsndfile reads: wav, ogg, mp3) into one audio file when the name's extension
    is an audio format (AudioFile: on the hub's disk, one file read at a time, a pause between them, converted to the
    first file's channels and rate), else text files into one text file (a blank line between them, at most
    MAX_TEXT_BYTES). a plain name is kept as TTS/<hash>/<name> (audio) or DOCUMENTS/<hash>/<name> (text), a full path is
    written there, a file there replaced only with overwrite (ShareFileTool._write)"""
    description = prompts.JOIN_FILES_DESCRIPTION
    max_attach_bytes = MAX_AUDIO_BYTES  # one file, held in memory once while it is written and attached, a larger one stays in the files
    sequential = False
    offered_with = ()
    thresholds = (0.65, 0.7)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user ask to join several existing files into one file?",
        "Does the user ask to join existing audio files (mp3, wav, ogg) into one audio file?",
        "Does the user ask to concatenate several existing text files into one file?",
    ]

    @classmethod
    def name(cls) -> str:
        return "join_files"

    def runs_detached(self) -> bool:
        """only an agent job's workers and task passes use it (ToolRegistry.CHAT_EXCLUDED_TOOLS): they wait for it"""
        return False

    def _checked(self) -> Tuple[str, str, bool, List[str]]:
        """(the name, its extension in lower case, whether it is a full path in the sandbox files, the paths to join) of
        the call, ValueError when it is not valid: a name with an extension or a full path (SandboxVolume.file_path), and
        at least two paths"""
        given = str(self.tool_call.get("name") or "").strip()
        full = SandboxVolume.file_path(given)
        name = full or sanitize_relative_path(given)
        if not name or not posixpath.splitext(name)[1]:
            raise ValueError("no valid name, give a file name with its extension like book.mp3 or notes.md, "
                             "or a full path like ~/projects/book/book.mp3")
        paths = self.tool_call.get("files")
        paths = [paths] if isinstance(paths, str) else [path for path in paths or [] if isinstance(path, str) and path.strip()]
        if not paths:
            raise ValueError("give the files to join, in their order")
        return name, posixpath.splitext(name)[1].lower(), full is not None, paths

    def _joined(self, name: str, extension: str, full: bool, paths: List[str]) -> Tuple[str, bytes, int, float | None]:
        """(the name of the file made, its bytes, how many files were joined, the audio's seconds or None for text).
        ValueError (a path, too few files, the output among them, not text), AudioFailed (not audio)"""
        files = self.volume().read_paths(paths, self.get_conversation_id(), MAX_AUDIO_BYTES if extension in FORMATS else MAX_TEXT_BYTES)
        count = 0
        if extension in FORMATS:
            with AudioFile() as audio:
                for source, data in files:
                    self._check_source(source, name, full)
                    audio.pause()
                    audio.append_file(data, source)
                    count += 1
                self._check_count(count)
                made, data = audio.finish(extension)
                return f"{posixpath.splitext(name)[0]}{made}", data, count, audio.seconds()
        texts, size = [], 0
        for source, data in files:
            self._check_source(source, name, full)
            if not is_text(data):
                raise ValueError(f"{source} is not a text file, text files and audio files can not be mixed")
            size += len(data)
            if size > MAX_TEXT_BYTES:
                raise ValueError(f"the joined text is larger than {MAX_TEXT_BYTES // (1024 * 1024)} MB")
            texts.append(data.decode("utf-8").strip("\n"))
            count += 1
        self._check_count(count)
        return name, ("\n\n".join(texts) + "\n").encode("utf-8"), count, None

    @staticmethod
    def _check_source(source: str, name: str, full: bool) -> None:
        if full and source == name:
            raise ValueError(f"{MOUNT_PATH}/{name} is one of the files to join, give the new file another name")

    @staticmethod
    def _check_count(count: int) -> None:
        if count < 2:
            raise ValueError(f"only {count} file to join, give at least two")

    def execute(self) -> None:
        given = self.tool_call.get("name")
        MessageQueue().send_status_message("joining files")
        try:
            name, extension, full, paths = self._checked()
            self._check_free(name, full)    # before the work: no minutes of joining for a file that is there
            made, data, count, seconds = self._joined(name, extension, full, paths)
            real, stored = (posixpath.basename(made), made) if full else \
                (made, (SandboxVolume.tts_path if seconds is not None else SandboxVolume.document_path)(made, data))
            self._write(stored, data, full)
        except (ValueError, AudioFailed) as e:
            self._failed(given, str(e))
            return
        except Exception as e:
            logger.error(f"join_files {given} failed {repr(e)}")
            self._failed(given, type(e).__name__)
            return
        length = prompts.JOIN_FILES_AUDIO_PART.format(minutes=f"{seconds / 60:.1f}") if seconds is not None else ""
        self.add_result(self._kept(real, stored, data, prompts.JOIN_FILES_MADE_PART.format(name=real, count=count, length=length)))

    def _failed(self, name, reason: str) -> None:
        logger.warning(f"join_files {name}: {reason}")
        self.add_result({"tool": self.name(), "error": reason, "text": prompts.JOIN_FILES_FAILED_PART.format(name=name, reason=reason)})

    @classmethod
    def prompt(cls) -> str:
        return prompts.JOIN_FILES_PROMPT.format(files=MOUNT_PATH, tts=f"{MOUNT_PATH}/{TTS}", documents=f"{MOUNT_PATH}/{DOCUMENTS}")
