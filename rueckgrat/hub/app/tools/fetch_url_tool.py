import re
from typing import Dict,  Any
from .websearch_tool import WebsearchTool
from app.tasks.summarize_task import SummarizeTask
from app.utils.url_check import check_url, FetchBlocked

from app.common import get_logger, MessageQueue
logger = get_logger()


def normalize_url(url: str) -> str:
    """feed:// and rss:// links are plain https feeds. without a scheme: http:// for localhost and IPs, https:// else"""
    url = re.sub(r"^(?:feed|rss)://", "https://", url, flags=re.IGNORECASE)
    if not re.match(r"[a-z][a-z0-9+.-]*://", url, flags=re.IGNORECASE):
        local = re.match(r"(?:localhost|\d{1,3}(?:\.\d{1,3}){3})(?![\w.-])", url, flags=re.IGNORECASE)
        url = ("http://" if local else "https://") + url
    return url


class FetchUrlTool(WebsearchTool):
    """subclass of WebsearchTool only to reuse _extract_page and _get_org_name, everything else is its own"""
    description = "reads a web page the user gives a link to and returns a condensed summary of it"
    question = []    # not a laya question: ToolDetectionTask selects it from URL_PATTERN in the message
    PAGE_TIMEOUT = 20           # one page the user is waiting for, not a batch
    BROWSER_FALLBACK = True     # the user asked for this page, worth a headless browser if plain http comes back thin

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "fetch_url"

    def execute(self) -> None:
        if not "url" in self.tool_call:
            logger.error("invalid fetch_url")
            return None

        url = normalize_url(str(self.tool_call["url"]).strip())
        focus = self.tool_call.get("focus") or None
        MessageQueue().send_status_message("reading the page")

        try:
            check_url(url)
            page = self._extract_page(url)
            if not page:
                logger.error(f"failed to extract page {url}")
                return
            
            summarize_task = SummarizeTask(text=page["text"], focus=focus, infrastructure=self.infrastructure)
            self.add_sub_task(summarize_task)
            self.wait_for([summarize_task])
            summary_result = summarize_task.get_result()
            if not summary_result or not "summary" in summary_result:
                logger.error(f"failed to extract page {url}")
                return

            summary = summary_result["summary"]
            result = {
                "tool": self.name(), 
                "text": f"{summary} - source {self._get_org_name(page['url'])} ({page['url']})"
            }

            self.add_result(result)
            self.add_source(page["url"])
            
        except FetchBlocked as e:
            logger.error(f"failed to fetch {url} {repr(e)}")
        except Exception as e:
            logger.error(f"failed to fetch {url} {repr(e)}")

    @classmethod
    def prompt(cls) -> str:
        return """
FETCH_URL:
Use when the user gives a URL and wants to know what is on the page.

Parameters:
- url (string, required): the full URL
- focus (string, optional): what to focus on (omit for general summary)

Example:
{"tool": "fetch_url", "url": "https://example.com/article", "focus": "release date"}
"""
