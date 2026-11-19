from typing import Dict, Any, Optional
import re
import requests
from urllib.parse import quote
from .tool import Tool
from . import prompts
from app.utils.library import Library, LibraryError

from app.common import get_logger, MessageQueue
logger = get_logger()

# Wikipedia's public REST API, no key. Wikimedia asks for a descriptive User-Agent
WIKIPEDIA_SEARCH_URL = "https://{lang}.wikipedia.org/w/rest.php/v1/search/title"
WIKIPEDIA_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIPEDIA_HEADERS = {"User-Agent": "Rueckgrat/1.0 (self-hosted personal assistant)", "Accept": "application/json"}
WIKIPEDIA_TIMEOUT = 10
MAX_SUMMARY_LENGTH = 1500


class WikipediaError(Exception):
    pass


class WikipediaUnreachable(WikipediaError):
    """Wikipedia did not answer (no internet, an error): the offline library is asked instead"""


def wikipedia_summary(query: str, lang: str = "en") -> Dict[str, str]:
    """returns {"title", "summary", "url"} of the best matching article"""
    lang = str(lang or "en").strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", lang):
        raise WikipediaError(f"invalid language code '{lang}'")
    try:
        resp = requests.get(WIKIPEDIA_SEARCH_URL.format(lang=lang), params={"q": query, "limit": 1}, headers=WIKIPEDIA_HEADERS, timeout=WIKIPEDIA_TIMEOUT)
        resp.raise_for_status()
        pages = resp.json().get("pages", [])
        if not pages:
            raise WikipediaError(f"no Wikipedia article found for '{query}'")

        resp = requests.get(WIKIPEDIA_SUMMARY_URL.format(lang=lang, title=quote(pages[0]["key"], safe="")), headers=WIKIPEDIA_HEADERS, timeout=WIKIPEDIA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except WikipediaError:
        raise
    except Exception as e:
        logger.warning(f"wikipedia request failed {repr(e)}")
        raise WikipediaUnreachable(f"Wikipedia unreachable ({type(e).__name__})")

    summary = (data.get("extract") or "").strip()
    if not summary:
        raise WikipediaError(f"the article '{data.get('title', query)}' has no summary")
    if data.get("type") == "disambiguation":
        summary = "(disambiguation page, the term has several meanings) " + summary
    if len(summary) > MAX_SUMMARY_LENGTH:
        summary = summary[:MAX_SUMMARY_LENGTH].rsplit(" ", 1)[0] + " ..."
    url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
    return {"title": data.get("title", query), "summary": summary, "url": url}


def library_summary(library: Library, query: str, lang: str = "en") -> Dict[str, str]:
    """the same as wikipedia_summary from the offline library's Wikipedia: {"title", "summary", "url", "book"}"""
    try:
        book = library.wikipedia_book(lang)
        if book is None:
            raise WikipediaError("the offline library has no Wikipedia")
        article = library.lookup(book["id"], query)
    except LibraryError as e:
        raise WikipediaError(str(e))
    if article is None:
        raise WikipediaError(f"no article found for '{query}' in the offline library")
    summary = Library.lead_text(article["html"], MAX_SUMMARY_LENGTH)
    if not summary:
        raise WikipediaError(f"the article '{article['title']}' has no summary")
    return {"title": article["title"], "summary": summary, "url": article["url"], "book": book["title"]}


class WikipediaTool(Tool):
    description = prompts.WIKIPEDIA_DESCRIPTION
    requires_any = ("internet", "library")     # Wikipedia online, else the offline library's copy
    thresholds = (0.4, 0.5)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user ask who a famous person from history was?",
        "Does the user ask to have a science theory or natural process explained?",
        "Does the user ask what a science term means, like photosynthesis or a black hole?",
        "Does the user ask you to tell them about a famous landmark, monument, war, treaty or historic event?",
        "Does the user ask about the history of a country, an empire or an era?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "wikipedia"

    def execute(self) -> None:
        if not "query" in self.tool_call:
            logger.error("invalid wikipedia")
            return None

        query = self.tool_call["query"]
        lang = self.tool_call.get("lang", "en")
        MessageQueue().send_status_message("looking it up on Wikipedia")

        try:
            article = self._lookup(query, lang)
            source = f"{article['book']} (offline library)" if article.get("book") else "Wikipedia"
            result = {"tool": self.name(), "text": f"{article['title']}: {article['summary']} - source {source} {article['url']}"}
            if article["url"]:
                self.add_source(article["url"], article["title"])
        except WikipediaError as e:
            logger.warning(f"wikipedia {query} failed: {e}")
            result = {"tool": self.name(), "error": str(e)}
        except Exception as e:
            logger.error(f"failed to query wikipedia {repr(e)}")
            result = {"tool": self.name(), "error": "Wikipedia lookup failed"}

        self.add_result(result)

    def _library(self) -> Optional[Library]:
        nomad = self.infrastructure.nomad() if self.infrastructure is not None else None
        return nomad.library() if nomad is not None else None

    def _lookup(self, query: str, lang: str) -> Dict[str, str]:
        """Wikipedia online, the offline library when the internet is not there or Wikipedia does not answer"""
        online = self.infrastructure is None or self.infrastructure.available("internet")
        library = self._library()
        if online:
            try:
                return wikipedia_summary(query, lang)
            except WikipediaUnreachable:
                if library is None:
                    raise
                logger.info(f"wikipedia {query!r}: unreachable, asking the offline library")
        if library is None:
            raise WikipediaError("Wikipedia needs the internet, which is not available right now")
        return library_summary(library, query, lang)

    @classmethod
    def prompt(cls) -> str:
        return prompts.WIKIPEDIA_PROMPT
