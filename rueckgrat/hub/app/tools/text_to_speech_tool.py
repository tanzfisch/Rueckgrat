import posixpath
from typing import Dict, Any, Iterator, List, Tuple
from . import prompts
from .share_file_tool import ShareFileTool
from app.utils.speech_file import SpeechFile, SpeechFailed
from app.utils.audio_file import FORMATS, MAX_AUDIO_BYTES
from app.utils.text_files import sanitize_relative_path, is_text
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH, TTS

from app.common import get_logger, MessageQueue, Utils
logger = get_logger()

MAX_TEXT_BYTES = 10 * 1024 * 1024   # of one text file read, about 15 hours of speech


class TextToSpeechTool(ShareFileTool):
    """speaks a short text of the call, or text files of the contact's sandbox files in their order, with the user's
    chosen voice or else the contact's (_voice) into one audio file (SpeechFile: chunk by chunk, so a long text never passes through the llm), kept as
    TTS/<hash>/<name>.wav, or .ogg when large, or in the format the name's extension asks for (.wav, .ogg, .mp3:
    AudioFile.finish) (SandboxVolume.tts_path), or at the full path the name gives (~/projects/x/book:
    SandboxVolume.file_path, a file there replaced only with overwrite: ShareFileTool._write), and offers it to the user
    like write_file does (ShareFileTool._kept). larger than MAX_AUDIO_BYTES it stays in the files.
    needs the tts node: without it the tool is not offered"""
    description = prompts.TEXT_TO_SPEECH_DESCRIPTION
    requires = ("tts",)
    max_attach_bytes = MAX_AUDIO_BYTES  # one file, held in memory once while it is written and attached, a larger one stays in the files
    sequential = False
    offered_with = ()
    thresholds = (0.55, 0.72)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user want an audio file made from a text?",
        "Does the user ask you to create an mp3 or audio version of a text?",
        "Does the user ask you to produce an audio recording of written text?",
        "Does the message ask to speak or narrate text files into an mp3 or audio file?",
    ]

    @classmethod
    def name(cls) -> str:
        return "text_to_speech"

    def runs_detached(self) -> bool:
        """speaking takes long (minutes for a chapter), in the chat the audio is attached when it is ready"""
        return True

    def _checked(self) -> Tuple[str, str, bool, str, List[str]]:
        """(the file name without extension, the extension it asks for or "", whether it is a full path in the sandbox
        files, the text or "", the paths) of the call, ValueError when it is not valid: a name or a full path (SandboxVolume.file_path), and either text or
        files"""
        given = str(self.tool_call.get("name") or "").strip()
        full = SandboxVolume.file_path(given)
        name = full or sanitize_relative_path(given)
        if not name:
            raise ValueError("no valid name, give a file name like story or books/chapter_1, or a full path like ~/projects/book/book")
        text = self.tool_call.get("text")
        text = text.strip() if isinstance(text, str) else ""
        paths = self.tool_call.get("files")
        paths = [paths] if isinstance(paths, str) else [path for path in paths or [] if isinstance(path, str) and path.strip()]
        if bool(text) == bool(paths):
            raise ValueError("give either text or files")
        base, extension = posixpath.splitext(name)
        return base, extension, full is not None, text, paths

    def _texts(self, text: str, paths: List[str]) -> Iterator[Tuple[str, str]]:
        """(where it is from, the text) in the order to speak: the call's text, or the files one at a time, a folder's
        files by name (SandboxVolume.read_paths). ValueError for a path that is not a text file in the sandbox files"""
        if text:
            yield "text", text
            return
        for name, data in self.volume().read_paths(paths, self.get_conversation_id(), MAX_TEXT_BYTES):
            if not is_text(data):
                raise ValueError(prompts.TEXT_TO_SPEECH_NOT_TEXT_PART.format(name=name))
            yield name, data.decode("utf-8")

    def _voice(self) -> str:
        """the voice the user chose for this tool (user settings, while it is still one of their voices), else the
        contact's voice (the user's voice uuid), "" the tts node's default"""
        user_id = self.get_user_id()
        chosen = self.db.get_user_tts_voice(user_id) if user_id is not None else None
        if chosen and self.db.find_user_voice(user_id, chosen):
            return chosen
        contact = self.db.get_contact_by_id(self.contact_id) or {}
        return Utils.get_nested_value(contact, ["profile", "tts_parameters", "voice_id"], "") or ""

    def execute(self) -> None:
        name = self.tool_call.get("name")
        MessageQueue().send_status_message("making audio")
        try:
            base, wanted, full, text, paths = self._checked()
            if full and wanted.lower() in FORMATS:     # known before speaking: no minutes of work for a file that is there
                self._check_free(f"{base}{wanted.lower()}", True)
            with SpeechFile(self.infrastructure, self._voice(), str(self.tool_call.get("language") or ""), background=self.background()) as speech:
                for source, content in self._texts(text, paths):
                    logger.debug(f"text_to_speech: speaking {source}")
                    speech.speak(content)
                extension, data = speech.finish(wanted)
                seconds = speech.seconds()
            audio = f"{base}{extension}"
            real, stored = (posixpath.basename(audio), audio) if full else (audio, SandboxVolume.tts_path(audio, data))
            self._write(stored, data, full)
        except (ValueError, SpeechFailed) as e:
            self._failed(name, str(e))
            return
        except Exception as e:
            logger.error(f"text_to_speech {name} failed {repr(e)}")
            self._failed(name, type(e).__name__)
            return
        self.add_result(self._kept(real, stored, data, prompts.TEXT_TO_SPEECH_MADE_PART.format(name=real, minutes=f"{seconds / 60:.1f}")))

    def _failed(self, name, reason: str) -> None:
        logger.warning(f"text_to_speech {name}: {reason}")
        self.add_result({"tool": self.name(), "error": reason, "text": prompts.TEXT_TO_SPEECH_FAILED_PART.format(name=name, reason=reason)})

    def planned_result(self) -> Dict[str, Any]:
        """the call is checked now, speaking runs detached"""
        try:
            base, wanted, full, _, _ = self._checked()
            if full and wanted.lower() in FORMATS:
                self._check_free(f"{base}{wanted.lower()}", True)
        except ValueError as e:
            return {self.name(): {"tool": self.name(), "error": str(e),
                                  "text": prompts.TEXT_TO_SPEECH_FAILED_PART.format(name=self.tool_call.get("name"), reason=e)}}
        return {self.name(): {"tool": self.name(), "text": prompts.TEXT_TO_SPEECH_PLANNED_PART.format(name=base)}}

    @classmethod
    def prompt(cls) -> str:
        return prompts.TEXT_TO_SPEECH_PROMPT.format(files=MOUNT_PATH, tts=f"{MOUNT_PATH}/{TTS}")
