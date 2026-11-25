"""#198 the llm work of the transcribe app: a short summary of a transcript, and the enhanced copy's texts (filler
words out, grammar fixed). both run on the caller's thread (TaskQueue.run) from the hub's /transcripts endpoints"""
import json
import random
from typing import Any, Dict, Optional

from app.common import get_logger, Utils
from app.common.transcript_command import TranscriptCommand
from .task_queue import Task
from . import prompts
logger = get_logger()


class TranscriptSummaryTask(Task):
    """a few sentences about the transcript's text (its headings as "## ..." lines). a long one is summarized part by
    part first, then the parts' summaries together. result: {"summary"}, None if the llm failed"""
    PART_CHARS = 24000      # ~6000 tokens a part: fits a slot of the llama server (ctx 32000 / 2 parallel) with the reply

    def __init__(self, infrastructure, text: str):
        super().__init__()
        self.infrastructure = infrastructure
        self.text = text
        self.summary: Optional[str] = None

    def execute(self) -> None:
        try:
            self.summary = self._summarize(self.text)
        except Exception as e:
            logger.error(f"failed to summarize the transcript {repr(e)}")

    def _summarize(self, text: str) -> Optional[str]:
        parts = split_text(text, self.PART_CHARS)
        if len(parts) > 1:
            summaries = [self._ask(part) for part in parts]
            if not all(summaries):
                return None
            text = "\n\n".join(summaries)
        return self._ask(text)

    def _ask(self, text: str) -> Optional[str]:
        reply = self.infrastructure.chat(
            messages=[{"role": "system", "content": prompts.TRANSCRIPT_SUMMARY_PROMPT}, {"role": "user", "content": text}],
            temperature=0.3,
            seed=random.randint(0, 100000),
            max_new_tokens=512,
        )
        return reply.strip() if reply and reply.strip() else None

    def get_result(self) -> Dict[str, Any]:
        return {"summary": self.summary}


class TranscriptEnhanceTask(Task):
    """the texts of the segments without filler words and with the grammar fixed, one for one: a batch of segments
    is sent as a json list and has to come back as one of the same length (else each of its segments on its own).
    result: {"texts"}: the same length as the input, None where the llm gave nothing usable (the text stays)"""
    BATCH_CHARS = 3000
    BATCH_SEGMENTS = 25

    def __init__(self, infrastructure, texts: list[str]):
        super().__init__()
        self.infrastructure = infrastructure
        self.source = texts
        self.texts: list[Optional[str]] = [None] * len(texts)

    def execute(self) -> None:
        start = 0
        while start < len(self.source):
            end, size = start, 0
            while end < len(self.source) and end - start < self.BATCH_SEGMENTS and (end == start or size + len(self.source[end]) <= self.BATCH_CHARS):
                size += len(self.source[end])
                end += 1
            try:
                self._batch(start, end)
            except Exception as e:
                logger.error(f"failed to enhance segments {start}..{end} {repr(e)}")
            start = end

    def _batch(self, start: int, end: int):
        texts = self.source[start:end]
        n = len(texts)
        schema = {"type": "object", "required": ["segments"], "properties": {
            "segments": {"type": "array", "items": {"type": "string"}, "minItems": n, "maxItems": n}}}
        reply = self.infrastructure.chat(
            messages=[{"role": "system", "content": prompts.TRANSCRIPT_ENHANCE_PROMPT},
                      {"role": "user", "content": json.dumps({"segments": texts}, ensure_ascii=False)}],
            temperature=0.2,
            seed=random.randint(0, 100000),
            max_new_tokens=2048,
            json_schema=schema,
        )
        data = Utils.json_loads(reply) if reply else None
        enhanced = data.get("segments") if isinstance(data, dict) else None
        if isinstance(enhanced, list) and len(enhanced) == n:
            for i, text in enumerate(enhanced):
                self.texts[start + i] = self._checked(texts[i], text)
            return
        logger.warning(f"enhancing segments {start}..{end}: {len(enhanced) if isinstance(enhanced, list) else 'no'} texts for {n}, one by one")
        for i in range(start, end):
            reply = self.infrastructure.chat(
                messages=[{"role": "system", "content": prompts.TRANSCRIPT_ENHANCE_ONE_PROMPT},
                          {"role": "user", "content": self.source[i]}],
                temperature=0.2,
                seed=random.randint(0, 100000),
                max_new_tokens=1024,
            )
            self.texts[i] = self._checked(self.source[i], reply)

    @staticmethod
    def _checked(source: str, text) -> Optional[str]:
        """the llm's text if it is one and not much longer than the source (it answered or added things), else None"""
        if not isinstance(text, str):
            return None
        text = " ".join(text.split())
        return text if text and len(text) <= 1.5 * len(source) + 40 else None

    def get_result(self) -> Dict[str, Any]:
        return {"texts": self.texts}


def enhanceable(segment: dict) -> Optional[str]:
    """the text of a stored segment (get_transcript) the enhanced copy cleans up: what was said as shown (the user's
    edit, else as recognised). None for headings, voice commands and utterances edited to nothing: copied as they are"""
    if segment.get("kind") or TranscriptCommand.parse(segment["text"]):
        return None
    text = segment["text"] if segment.get("edited") is None else segment["edited"]
    return text if text.strip() else None


def split_text(text: str, size: int) -> list[str]:
    """text in parts of at most size characters, cut at paragraph breaks (else at spaces)"""
    parts, part = [], ""
    for paragraph in text.split("\n\n"):
        while len(paragraph) > size:        # one paragraph longer than a part: cut at the last space before size
            cut = paragraph.rfind(" ", 0, size)
            cut = cut if cut > 0 else size
            if part:
                parts.append(part)
                part = ""
            parts.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        if part and len(part) + 2 + len(paragraph) > size:
            parts.append(part)
            part = ""
        part = f"{part}\n\n{paragraph}" if part else paragraph
    if part:
        parts.append(part)
    return parts
