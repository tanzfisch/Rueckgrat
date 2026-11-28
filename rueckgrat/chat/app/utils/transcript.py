"""#198 one recording of the transcribe app: the text the hub recognised, one segment per utterance, and the bookmarks
tapped meanwhile, each with a label. all times are seconds of the recording: they only place the bookmarks in the text
and skip audio sent twice, the audio is not kept, so nothing shows them. the hub stores both (GET /transcripts/{id}),
this is the copy the page shows and exports.

the segments keep what was said. what is shown is interpreted here: the voice commands (app/common/transcript_command)
and the user's edits (Segment.edited, made after the recording). utterances run on in one paragraph until
"new paragraph", a heading or a bookmark. a bookmark sits in the text where its time is: inside an utterance at the word
boundary its time falls on (by the share of the utterance's time), so a bookmark set at the cursor stays there"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.common.transcript_command import TranscriptCommand

# a segment sent again after a reconnect overlaps the one already there (same as ChatDB.SEGMENT_OVERLAP on the hub)
SEGMENT_OVERLAP = 0.25
HEADING_GAP = 0.01      # an added heading sits this much before the segment after it, so it sorts in front of it
PREVIEW_WORDS = 8


def clock(seconds: float) -> str:
    """03:25, from an hour on 1:02:03"""
    s = int(max(0.0, seconds))
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def md_escape(text: str) -> str:
    """text that markdown shows as it is: its formatting characters and html get a backslash, and so does a line start
    that would make a heading, quote, list or rule"""
    text = re.sub(r"([\\`*_\[\]{}<>#|~!&])", r"\\\1", " ".join(text.split()))
    text = re.sub(r"^([-+=])", r"\\\1", text)
    return re.sub(r"^(\d+)([.)])", r"\1\\\2", text)       # 1. -> 1\. (a backslash before a digit stays visible)


def local_time(created_at: str) -> datetime | None:
    """the hub's CURRENT_TIMESTAMP (utc, "2026-11-16 01:30:00") in the local time zone, None if it is not one"""
    try:
        return datetime.fromisoformat(created_at).replace(tzinfo=timezone.utc).astimezone()
    except (TypeError, ValueError):
        return None


@dataclass(eq=False)     # by identity: the page keeps a control per segment
class Segment:
    start: float
    end: float
    text: str                   # as the hub recognised it, never changed
    id: int = 0                 # the hub's id, 0 while unknown (then it can not be edited)
    edited: str | None = None   # the user's text for it, None: not edited
    kind: str = ""              # HEADING: added by the user after the recording, text its words. "": said

    @property
    def command(self) -> TranscriptCommand | None:
        return TranscriptCommand(TranscriptCommand.HEADING, self.text) if self.kind == TranscriptCommand.HEADING else TranscriptCommand.parse(self.text)

    @property
    def shown(self) -> str:
        """its text as shown: the edit, else a heading's words or the text said"""
        if self.edited is not None:
            return self.edited.strip()
        command = self.command
        return command.get_argument() if command and command.get_kind() == TranscriptCommand.HEADING else self.text


@dataclass(eq=False)     # by identity: two bookmarks can have the same time
class Bookmark:
    at: float
    id: int = 0     # the hub's id, 0 while it is not stored (yet)
    label: str = ""


@dataclass
class Item:
    """one visible piece of the transcript: kind TEXT, HEADING or PARAGRAPH (a break) and its segment"""
    kind: str
    segment: Segment

TEXT = "text"


@dataclass
class Block:
    """what is shown, in order: a paragraph (its pieces: (segment, text)), a heading or a bookmark"""
    kind: str                   # PARAGRAPH, HEADING or BOOKMARK
    pieces: list[tuple[Segment, str]] = field(default_factory=list)
    bookmark: Bookmark | None = None

    @property
    def text(self) -> str:
        return " ".join(text for _, text in self.pieces if text)


def word_boundary(text: str, k: int) -> int:
    """the boundary between two words nearest to offset k (0 and len(text) count as boundaries)"""
    boundaries = [0, len(text)] + [m.start() for m in re.finditer(r"\s+", text)]
    return min(boundaries, key=lambda b: (abs(b - k), b))


@dataclass
class Transcript:
    id: int = 0
    language: str = ""
    created_at: str = ""    # utc, as the hub stores it
    duration: float = 0.0
    segments: list[Segment] = field(default_factory=list)
    bookmarks: list[Bookmark] = field(default_factory=list)
    stored_title: str = ""  # the hub's title, "": named by its date (title)

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        """the hub's GET /transcripts/{id}"""
        transcript = cls(id=data.get("id", 0), language=data.get("language", ""), created_at=data.get("created_at", ""),
                         duration=data.get("duration", 0.0), stored_title=data.get("title") or "")
        transcript.settle(data)
        return transcript

    def settle(self, data: dict):
        """the hub's copy after a recording (GET /transcripts/{id}): its segments with their ids and edits,
        its bookmarks plus the ones it has not got yet"""
        self.duration = max(self.duration, data.get("duration", 0.0))
        unsent = [b for b in self.bookmarks if b.id <= 0]
        self.segments, self.bookmarks = [], []
        for s in data.get("segments", []):
            segment = self.add_segment(s["start"], s["end"], s["text"], s.get("id", 0), s.get("kind") or "")
            if segment:
                segment.edited = s.get("edited")
        for b in data.get("bookmarks", []):
            self.add_bookmark(b["at"], b.get("id", 0), b.get("label", ""))
        for b in unsent:
            self.add_bookmark(b.at, b.id, b.label)

    def add_segment(self, start: float, end: float, text: str, segment_id: int = 0, kind: str = "") -> Segment | None:
        """a final text of the hub (or an added heading, kind HEADING), kept in time order. None if it is empty or
        overlaps a segment already there"""
        text = (text or "").strip()
        if not text or any(s.end > start + SEGMENT_OVERLAP and s.start < end - SEGMENT_OVERLAP for s in self.segments):
            return None
        segment = Segment(start, end, text, segment_id, kind=kind)
        index = next((i for i, s in enumerate(self.segments) if s.start > start), len(self.segments))
        self.segments.insert(index, segment)
        return segment

    def add_bookmark(self, at: float, bookmark_id: int = 0, label: str = "") -> Bookmark:
        bookmark = Bookmark(max(0.0, at), bookmark_id, label)
        index = next((i for i, b in enumerate(self.bookmarks) if b.at > bookmark.at), len(self.bookmarks))
        self.bookmarks.insert(index, bookmark)
        return bookmark

    def remove_bookmark(self, bookmark: Bookmark):
        self.bookmarks.remove(bookmark)

    def number(self, bookmark: Bookmark) -> int:
        """1 for the first bookmark in time"""
        return self.bookmarks.index(bookmark) + 1

    def next_label(self) -> str:
        """the label of a bookmark tapped now: Bookmark n, unique (next_bookmark_label), renamed later if wanted"""
        return TranscriptCommand.next_bookmark_label([b.label for b in self.bookmarks])

    def name(self, bookmark: Bookmark) -> str:
        """its label. one without (an older hub stored a spoken "bookmark" so): Bookmark n numbered on after the labelled
        ones, so it does not show the name of another one"""
        if bookmark.label.strip():
            return bookmark.label.strip()
        defaults = [b.label.strip() for b in self.bookmarks if b.label.strip().startswith("Bookmark ")]
        unlabelled = [b for b in self.bookmarks if not b.label.strip()]
        return f"Bookmark {TranscriptCommand.next_bookmark_number(defaults) + unlabelled.index(bookmark)}"

    ########### interpreting the voice commands and edits
    def items(self) -> list[Item]:
        """the visible pieces in order: "new paragraph" is a break, "heading ..." a heading, "bookmark ..." is not
        shown (the hub stored it as a bookmark), "scratch that" removes the piece before it. an utterance edited
        to nothing is not shown"""
        items: list[Item] = []
        for segment in self.segments:
            command = segment.command
            kind = command.get_kind() if command else TEXT
            if kind == TranscriptCommand.SCRATCH:     # the piece said before it: a heading added later between them stays
                said = [i for i, item in enumerate(items) if item.segment.kind != TranscriptCommand.HEADING]
                if said:
                    items.pop(said[-1])
            elif kind == TranscriptCommand.PARAGRAPH:
                items.append(Item(TranscriptCommand.PARAGRAPH, segment))
            elif kind in (TEXT, TranscriptCommand.HEADING) and segment.shown:
                items.append(Item(kind, segment))
        return items

    def anchor(self, bookmark: Bookmark, items: list[Item] | None = None) -> tuple[int, int]:
        """where the marker goes: (i, k) is offset k in the shown text of items[i], k 0 in front of it. inside an
        utterance at the word boundary its time falls on, in front of a heading or a break, in front of the next piece
        when it falls between two. (len(items), 0): behind the last one, e.g. tapped after the last text received"""
        items = self.items() if items is None else items
        for i, item in enumerate(items):
            segment = item.segment
            if bookmark.at >= segment.end:
                continue
            if item.kind != TEXT or bookmark.at <= segment.start:
                return i, 0
            text = segment.shown
            k = word_boundary(text, round(len(text) * (bookmark.at - segment.start) / (segment.end - segment.start)))
            return (i, k) if k < len(text) else (i + 1, 0)
        return len(items), 0

    def heading_time(self, segment: Segment | None, offset: int = 0) -> float:
        """the time of a heading added at the cursor (segment, offset): in front of the segment with the cursor at its
        start, else behind it (in front of the next one). no segment: behind the last one"""
        segments = self.segments
        if segment is None or segment not in segments:
            return (segments[-1].end if segments else 0.0) + HEADING_GAP
        if offset <= 0:
            return segment.start - HEADING_GAP
        i = segments.index(segment)
        following = segments[i + 1] if i + 1 < len(segments) else None
        return max(segment.start, following.start - HEADING_GAP) if following else segment.end + HEADING_GAP

    @staticmethod
    def time_at(segment: Segment, offset: int, text: str | None = None) -> float:
        """the time of offset in the segment's shown text (or text, its field's while it is edited): a bookmark at the
        cursor (anchor maps it back)"""
        text = segment.shown if text is None else text
        if not text or segment.end <= segment.start:
            return segment.start
        return segment.start + (segment.end - segment.start) * min(max(offset, 0), len(text)) / len(text)

    def split_parts(self, segment: Segment, text: str, start: int, end: int) -> list[dict]:
        """a marked text [start, end) of the segment's text (its field's) made a heading: the parts it becomes,
        [{start, end, text, kind}] in order: before (start .. the mark), the heading (no time, at the mark), after
        (the mark's end .. end), empty ones left out. the times keep each word where it was, so the bookmarks inside
        stay with their words (one inside the mark lands behind the heading). [] if the mark holds no words"""
        heading = " ".join(text[start:end].split())
        if not heading:
            return []
        t1, t2 = self.time_at(segment, start, text), self.time_at(segment, end, text)
        before, after = " ".join(text[:start].split()), " ".join(text[end:].split())
        parts = [{"start": segment.start, "end": t1, "text": before, "kind": ""}] if before else []
        parts.append({"start": t1, "end": t1, "text": heading, "kind": TranscriptCommand.HEADING})
        if after:
            parts.append({"start": t2, "end": segment.end, "text": after, "kind": ""})
        return parts

    def replace_segment(self, segment: Segment, parts: list[dict], ids: list[int]) -> list[Segment]:
        """the segment split into parts (split_parts) with the hub's ids, in its place"""
        new = [Segment(p["start"], p["end"], p["text"], i, kind=p["kind"]) for p, i in zip(parts, ids)]
        index = self.segments.index(segment)
        self.segments[index:index + 1] = new
        return new

    def blocks(self) -> list[Block]:
        """paragraphs, headings and bookmarks in reading order"""
        items = self.items()
        anchors: dict[int, list[tuple[int, Bookmark]]] = {}
        for bookmark in self.bookmarks:
            i, k = self.anchor(bookmark, items)
            anchors.setdefault(i, []).append((k, bookmark))
        blocks: list[Block] = []
        paragraph = Block(TranscriptCommand.PARAGRAPH)

        def flush():
            nonlocal paragraph
            if paragraph.pieces:
                blocks.append(paragraph)
            paragraph = Block(TranscriptCommand.PARAGRAPH)

        def mark(bookmark: Bookmark):
            flush()
            blocks.append(Block(TranscriptCommand.BOOKMARK, bookmark=bookmark))

        for i, item in enumerate(items + [None]):
            here = sorted(anchors.get(i, []), key=lambda a: a[0])     # stable: same offset keeps the time order
            for _, bookmark in [a for a in here if a[0] == 0]:
                mark(bookmark)
            if item is None:
                break
            if item.kind == TranscriptCommand.PARAGRAPH:
                flush()
            elif item.kind == TranscriptCommand.HEADING:
                flush()
                blocks.append(Block(TranscriptCommand.HEADING, pieces=[(item.segment, item.segment.shown)]))
            else:
                text, done = item.segment.shown, 0
                for k, bookmark in [a for a in here if a[0] > 0]:
                    paragraph.pieces.append((item.segment, text[done:k].strip()))
                    mark(bookmark)
                    done = k
                paragraph.pieces.append((item.segment, text[done:].strip()))
        flush()
        return blocks

    def preview(self, bookmark: Bookmark) -> str:
        """the first words after the marker"""
        blocks = self.blocks()
        index = next((i for i, b in enumerate(blocks) if b.bookmark is bookmark), len(blocks))
        following = next((b for b in blocks[index + 1:] if b.kind != TranscriptCommand.BOOKMARK and b.text), None)
        if following is None:
            return ""
        words = following.text.split()
        return " ".join(words[:PREVIEW_WORDS]) + (" …" if len(words) > PREVIEW_WORDS else "")

    @property
    def end(self) -> float:
        """seconds recorded, as far as known"""
        return max([self.duration] + [s.end for s in self.segments] + [b.at for b in self.bookmarks])

    @property
    def resume_at(self) -> float:
        """where a continued recording starts: after everything stored, so its times place and dedupe like one recording.
        edits do not change the times, the new text comes after the edited one"""
        return self.end

    def title(self) -> str:
        if self.stored_title:
            return self.stored_title
        local = local_time(self.created_at)
        return f"Transcript {local:%Y-%m-%d %H:%M}" if local else "Transcript"

    def enhanced_title(self) -> str:
        """the name of its enhanced copy"""
        return f"{self.title()} (enhanced)"

    def plain_text(self) -> str:
        """what is shown as plain text, the headings as ## lines, without the bookmarks: what the summary is made of"""
        return "\n\n".join(f"## {b.text}" if b.kind == TranscriptCommand.HEADING else b.text for b in self.blocks() if b.kind != TranscriptCommand.BOOKMARK and b.text)

    def file_name(self) -> str:
        local = local_time(self.created_at)
        return f"transcript_{local:%Y-%m-%d_%H%M}.md" if local else f"transcript_{self.id}.md"

    def to_markdown(self) -> str:
        """the export: # title, ## Contents with a link to each heading, ## Bookmarks with a link to each and the first
        words after it, ## Transcript with its paragraphs and ### headings. at each heading an <a id="heading-n"> (n: its
        place among the headings), at each bookmark an <a id="bookmark-n"> (n: its number, unique whatever the label)
        and its label as 🏷️ *label*"""
        lines = [f"# {md_escape(self.title())}", ""]
        blocks = self.blocks()
        headings = [b for b in blocks if b.kind == TranscriptCommand.HEADING]
        number = {id(b): n for n, b in enumerate(headings, 1)}     # by identity: two headings can read the same
        if headings:
            lines += ["## Contents", ""]
            lines += [f"- [{md_escape(b.text)}](#heading-{n})" for n, b in enumerate(headings, 1)]
            lines.append("")
        if self.bookmarks:
            lines += ["## Bookmarks", ""]
            for b in self.bookmarks:
                preview = self.preview(b)
                lines.append(f"- [{md_escape(self.name(b))}](#bookmark-{self.number(b)})" + (f" {md_escape(preview)}" if preview else ""))
            lines.append("")
        lines += ["## Transcript", ""]
        for block in blocks:
            if block.kind == TranscriptCommand.BOOKMARK:
                lines += [f'<a id="bookmark-{self.number(block.bookmark)}"></a>', "", f"🏷️ *{md_escape(self.name(block.bookmark))}*", ""]
            elif block.kind == TranscriptCommand.HEADING:
                lines += [f'<a id="heading-{number[id(block)]}"></a>', "", f"### {md_escape(block.text)}", ""]
            else:
                lines += [md_escape(block.text), ""]
        return "\n".join(lines).rstrip("\n") + "\n"
