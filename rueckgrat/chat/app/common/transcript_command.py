"""#198 voice commands of the transcribe app, english only. an utterance is a command only as a whole: "new paragraph",
"scratch that", "heading <words>" / "headline <words>", "bookmark [<label>]" (a comma or colon whisper puts after the
command word is ignored). the stored text stays as it was said, the transcript interprets it (app/utils/transcript.py);
the hub uses this too, to store the bookmark a command asks for"""
import re


class TranscriptCommand:
    PARAGRAPH, HEADING, BOOKMARK, SCRATCH = "paragraph", "heading", "bookmark", "scratch"
    MAX_ARG_WORDS = 8       # "heading north we went ..." is a sentence, not a command
    _EDGE = " \t\n.,;:!?-–—\"'“”„"
    _WITH_ARG = re.compile(r"^\W*(heading|headline|bookmark)\b(.*)$", re.IGNORECASE | re.DOTALL)
    _DEFAULT_LABEL = re.compile(r"^Bookmark (\d+)$")

    def __init__(self, kind: str, argument: str = ""):
        self._kind = kind
        self._argument = argument

    def get_kind(self) -> str:
        return self._kind

    def get_argument(self) -> str:
        return self._argument

    @classmethod
    def next_bookmark_number(cls, labels: list[str]) -> int:
        """n of the next Bookmark n: one above the highest Bookmark n there is (also of earlier recordings of the transcript,
        and after one was deleted) and above the number of bookmarks, so no two bookmarks get the same default label"""
        numbers = [int(m.group(1)) for m in (cls._DEFAULT_LABEL.match((label or "").strip()) for label in labels) if m]
        return max(numbers + [len(labels)]) + 1

    @classmethod
    def next_bookmark_label(cls, labels: list[str]) -> str:
        """the label of a new bookmark"""
        return f"Bookmark {cls.next_bookmark_number(labels)}"

    @classmethod
    def parse(cls, text: str) -> "TranscriptCommand | None":
        """the command of an utterance, None for text. the argument keeps its words as said"""
        words = re.sub(r"[^\w\s']", " ", text or "").lower().split()
        if words == ["new", "paragraph"]:
            return cls(cls.PARAGRAPH)
        if words == ["scratch", "that"]:
            return cls(cls.SCRATCH)
        match = cls._WITH_ARG.match((text or "").strip())
        if not match:
            return None
        keyword, argument = match.group(1).lower(), match.group(2).strip(cls._EDGE)
        if len(argument.split()) > cls.MAX_ARG_WORDS:
            return None
        if keyword == "bookmark":
            return cls(cls.BOOKMARK, argument)
        return cls(cls.HEADING, argument) if argument else None
