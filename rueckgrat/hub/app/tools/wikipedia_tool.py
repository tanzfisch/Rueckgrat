from typing import Dict,  Any
import re
import requests
from urllib.parse import quote
from .tool import Tool, ToolCategory

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
        raise WikipediaError(f"Wikipedia unreachable ({type(e).__name__})")

    summary = (data.get("extract") or "").strip()
    if not summary:
        raise WikipediaError(f"the article '{data.get('title', query)}' has no summary")
    if data.get("type") == "disambiguation":
        summary = "(disambiguation page, the term has several meanings) " + summary
    if len(summary) > MAX_SUMMARY_LENGTH:
        summary = summary[:MAX_SUMMARY_LENGTH].rsplit(" ", 1)[0] + " ..."
    url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
    return {"title": data.get("title", query), "summary": summary, "url": url}


class WikipediaTool(Tool):
    category = ToolCategory.WEB
    description = "encyclopedic summary of a well known person, place, thing, concept or historic event"
    question = "Does the user want to know about a well known topic?"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "wikipedia"

    def execute(self) -> None:
        if not "query" in self.tool_call:
            logger.error("invalid wikipedia")
            return None

        query = self.tool_call["query"]
        MessageQueue().send_status_message("looking it up on Wikipedia")

        try:
            article = wikipedia_summary(query, self.tool_call.get("lang", "en"))
            result = {"tool": self.name(), "text": f"{article['title']}: {article['summary']} - source Wikipedia {article['url']}"}
            if article["url"]:
                MessageQueue().send_url(article["url"])
        except WikipediaError as e:
            logger.warning(f"wikipedia {query} failed: {e}")
            result = {"tool": self.name(), "error": str(e)}
        except Exception as e:
            logger.error(f"failed to query wikipedia {repr(e)}")
            result = {"tool": self.name(), "error": "Wikipedia lookup failed"}

        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
WIKIPEDIA:
Use for a quick encyclopedic summary of a well-known person, place, thing, or event. Not for news or current values.

Parameters:
- query (string, required): the topic
- lang (string, optional): Wikipedia language code, default "en"

Example:
{"tool": "wikipedia", "query": "Eiffel Tower", "lang": "en"}
"""
