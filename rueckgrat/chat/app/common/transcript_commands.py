"""#198 voice commands of the transcribe app, english only. an utterance is a command only as a whole: "new paragraph",
"scratch that", "heading <words>" / "headline <words>", "bookmark [<label>]" (a comma or colon whisper puts after the
command word is ignored). the stored text stays as it was said, the transcript interprets it (app/utils/transcript.py);
the hub uses this too, to store the bookmark a command asks for"""
import re

PARAGRAPH, HEADING, BOOKMARK, SCRATCH = "paragraph", "heading", "bookmark", "scratch"
MAX_ARG_WORDS = 8       # "heading north we went ..." is a sentence, not a command
_EDGE = " \t\n.,;:!?-–—\"'“”„"
_WITH_ARG = re.compile(r"^\W*(heading|headline|bookmark)\b(.*)$", re.IGNORECASE | re.DOTALL)
_DEFAULT_LABEL = re.compile(r"^Bookmark (\d+)$")


def next_bookmark_number(labels: list[str]) -> int:
    """n of the next Bookmark n: one above the highest Bookmark n there is (also of earlier recordings of the transcript,
    and after one was deleted) and above the number of bookmarks, so no two bookmarks get the same default label"""
    numbers = [int(m.group(1)) for m in (_DEFAULT_LABEL.match((label or "").strip()) for label in labels) if m]
    return max(numbers + [len(labels)]) + 1


def next_bookmark_label(labels: list[str]) -> str:
    """the label of a new bookmark"""
    return f"Bookmark {next_bookmark_number(labels)}"


def parse_command(text: str) -> tuple[str, str] | None:
    """(kind, argument) of an utterance that is a command, None for text. the argument keeps its words as said"""
    words = re.sub(r"[^\w\s']", " ", text or "").lower().split()
    if words == ["new", "paragraph"]:
        return PARAGRAPH, ""
    if words == ["scratch", "that"]:
        return SCRATCH, ""
    match = _WITH_ARG.match((text or "").strip())
    if not match:
        return None
    keyword, argument = match.group(1).lower(), match.group(2).strip(_EDGE)
    if len(argument.split()) > MAX_ARG_WORDS:
        return None
    if keyword == "bookmark":
        return BOOKMARK, argument
    return (HEADING, argument) if argument else None
