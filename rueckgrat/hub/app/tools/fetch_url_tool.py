from typing import Dict,  Any
import ipaddress
import socket
from urllib.parse import urlparse
from .tool import ToolCategory
from .websearch_tool import WebsearchTool
from app.jobs.summarize_job import SummarizeJob

from app.common import get_logger, MessageQueue
logger = get_logger()


def is_public_http_url(url: str) -> bool:
    """only http(s) urls whose host resolves to public addresses. keeps the hub from fetching
    localhost, the docker network or the lan on behalf of the model (SSRF)"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except (ValueError, socket.gaierror, UnicodeError) as e:
        logger.warning(f"fetch_url: can't resolve {url}: {repr(e)}")
        return False

    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])     # strip an ipv6 zone id
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            logger.warning(f"fetch_url: {url} resolves to non public address {ip}")
            return False
    return bool(infos)


class FetchUrlTool(WebsearchTool):
    """subclass of WebsearchTool only to reuse _extract_page and _get_org_name, everything else is its own"""
    category = ToolCategory.WEB
    description = "reads a web page the user gives a link to and returns a condensed summary of it"

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
            if not is_public_http_url(url):
                result = {"tool": self.name(), "error": f"can only read public http(s) web pages, not '{url}'"}
            else:
                page = self._extract_page(url)
                if not page:
                    result = {"tool": self.name(), "error": "could not read the page (unreachable, empty or needs JavaScript)"}
                else:
                    job = SummarizeJob(text=page["text"], focus=focus, infrastructure=self.infrastructure)
                    self.add_sub_job(job)
                    self.wait_for([job])
                    summary = job.result()
                    if summary:
                        result = {"tool": self.name(), "text": f"{summary} - source {self._get_org_name(page['url'])} ({page['url']})"}
                        MessageQueue().send_url(page["url"])
                    else:
                        result = {"tool": self.name(), "error": "could not summarize the page"}
        except Exception as e:
            logger.error(f"failed to fetch {url} {repr(e)}")
            result = {"tool": self.name(), "error": "reading the page failed"}

        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
FETCH_URL:

Use the fetch_url tool when the user gives a link (URL) and wants to know what is on that page, e.g. "summarize this", "what does this article say". url is the full link from the message, focus is optional (what to pay attention to, leave it out for a general summary):
{
  "tool": "fetch_url",
  "url": "https://example.com/article",
  "focus": "release date"
}
"""
