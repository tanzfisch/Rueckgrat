from .job_queue import Job
from typing import Optional
import random

from app.common import get_logger
from app.utils.content_filter import strip_html_boilerplate, strip_text_noise
logger = get_logger()

MIN_CONTENT_LENGTH = 200    # less than this after cleanup is not worth a summary (empty or JS only page)

class SummarizeJob(Job):
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

    def result(self) -> Optional[str]:
        return self.summary

    def _prepare(self) -> str:
        """filter first, then cap, so max_chars is spent on content and not on menus"""
        raw = strip_html_boilerplate(self.html) if self.html else (self.text or "")
        return strip_text_noise(raw)[:self.max_chars]

    def _summarize(self) -> Optional[str]:
        content = self._prepare()
        if len(content) < MIN_CONTENT_LENGTH:
            logger.warning(f"nothing to summarize, only {len(content)} characters left after cleanup")
            return None

        focus = f"\nFocus on: {self.focus}" if self.focus else ""
        query = f"""TEXT:
{content}

Summarize the main content of the TEXT in at most {self.max_words} words.{focus}
Leave out navigation, ads and cookie notices. Reply with the summary only.
"""
        logger.debug(f"summarize query:\n{query}")

        messages = [
            {"role": "system", "content": "You summarize web pages accurately. Use only the given text."},
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
