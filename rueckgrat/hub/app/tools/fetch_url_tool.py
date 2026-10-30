from typing import Dict,  Any
from .tool import ToolCategory
from .websearch_tool import WebsearchTool
from app.jobs.summarize_job import SummarizeJob
from app.utils.url_check import check_url, FetchBlocked

from app.common import get_logger, MessageQueue
logger = get_logger()


class FetchUrlTool(WebsearchTool):
    """subclass of WebsearchTool only to reuse _extract_page and _get_org_name, everything else is its own"""
    category = ToolCategory.WEB
    description = "reads a web page the user gives a link to and returns a condensed summary of it"
    question = "Does the user want you to read a web page they linked?"
    PAGE_TIMEOUT = 20           # one page the user is waiting for, not a batch
    BROWSER_FALLBACK = True     # the user asked for this page, worth a headless browser if plain http comes back thin

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "fetch_url"

    def execute(self) -> None:
        if not "url" in self.tool_call:
            logger.error("invalid fetch_url")
            return None

        url = str(self.tool_call["url"]).strip()
        focus = self.tool_call.get("focus") or None
        MessageQueue().send_status_message("reading the page")

        try:
            check_url(url)      # the clear reason up front. _extract_page checks again, pinned, and every redirect
            page = self._extract_page(url)
            if not page:
                if getattr(self, "blocked_reason", None):
                    result = {"tool": self.name(), "error": self.blocked_reason}
                else:
                    result = {"tool": self.name(), "error": "could not read the page (unreachable, empty or needs JavaScript)"}
            else:
                job = SummarizeJob(text=page["text"], focus=focus, infrastructure=self.infrastructure)
                self.add_sub_job(job)
                self.wait_for([job])
                summary = job.result()
                if summary:
                    result = {"tool": self.name(), "text": f"{summary} - source {self._get_org_name(page['url'])} ({page['url']})"}
                    self.add_source(page["url"])
                else:
                    result = {"tool": self.name(), "error": "could not summarize the page"}
        except FetchBlocked as e:
            result = {"tool": self.name(), "error": str(e)}
        except Exception as e:
            logger.error(f"failed to fetch {url} {repr(e)}")
            result = {"tool": self.name(), "error": "reading the page failed"}

        self.response.setdefault("tool_results", []).append(result)

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
