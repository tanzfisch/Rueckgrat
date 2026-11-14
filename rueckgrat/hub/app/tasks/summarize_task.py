from .task_queue import Task
from . import prompts
from typing import Optional
import random
from typing import Dict, Any

from app.common import get_logger
from app.utils.content_filter import strip_html_boilerplate, strip_text_noise
logger = get_logger()

MIN_CONTENT_LENGTH = 200    # less than this after cleanup is not worth a summary (empty or JS only page)

class SummarizeTask(Task):
    """condenses one page into a short plain text summary. give it the page text or the raw html (html wins),
    the content filter strips the noise (menus, ads, cookie banners) before the llm sees it. result() is the summary or None"""
    def __init__(self, infrastructure, text: Optional[str] = None, html: Optional[str] = None,
                 focus: Optional[str] = None, max_words: int = 150, max_chars: int = 12000):
        super().__init__()
        self.infrastructure = infrastructure
        self.text = text
        self.html = html
        self.focus = focus
        self.max_words = max_words
        self.max_chars = max_chars
        self.summary = None

    def execute(self) -> None:
        try:
            self.summary = self._summarize()
        except Exception as e:
            logger.error(f"failed to summarize {repr(e)}")

    def get_result(self) -> Dict[str, Any]:
        return {"summary": self.summary}

    def _prepare(self) -> str:
        """filter first, then cap, so max_chars is spent on content and not on menus"""
        raw = strip_html_boilerplate(self.html) if self.html else (self.text or "")
        return strip_text_noise(raw)[:self.max_chars]

    def _summarize(self) -> Optional[str]:
        content = self._prepare()
        if len(content) < MIN_CONTENT_LENGTH:
            logger.warning(f"nothing to summarize, only {len(content)} characters left after cleanup")
            return None

        focus = prompts.SUMMARIZE_FOCUS_PART.format(focus=self.focus) if self.focus else ""
        query = prompts.SUMMARIZE_PROMPT.format(content=content, max_words=self.max_words, focus=focus)
        logger.debug(f"summarize query:\n{query}")

        messages = [
            {"role": "system", "content": prompts.SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        response_content = self.infrastructure.chat(
            messages=messages,
            temperature=0.2,
            seed=random.randint(0, 100000)
        )
        if not response_content or not response_content.strip():
            logger.error("failed summarize query")
            return None
        return response_content.strip()
