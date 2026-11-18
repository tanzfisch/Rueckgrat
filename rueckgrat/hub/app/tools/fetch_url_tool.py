import re
from typing import Dict,  Any
from .websearch_tool import WebsearchTool
from . import prompts
from app.tasks.summarize_task import SummarizeTask
from app.utils.url_check import check_url, is_local_host, FetchBlocked

from app.common import get_logger, MessageQueue
logger = get_logger()

# a link in the message selects fetch_url (FetchUrlTool.text_score), no laya question
TLDS = r"com|org|net|edu|gov|mil|int|info|biz|io|ai|app|dev|xyz|online|site|tech|blog|news|shop|store|cloud|page|link|live|media|tv"
NOT_TLDS = r"py|md|sh|rs|pl|cc|cs|so|ps|hs|ml|mk|tf|pm|gz|js|ts|rb|kt|go|db"
URL_PATTERN = re.compile(rf"""
    [a-z][a-z0-9+.-]*://\S+                                   # any scheme, also glued to a word: protestshttps://...
  | \bwww\.[\w-]+\.\S+                                       # www.example.org
  | \blocalhost(?::\d+|/)\S*                                 # localhost:8080, localhost/x
  | (?<![\w.])(?:\d{{1,3}}\.){{3}}\d{{1,3}}(?!\.?\d)(?::\d+)?(?:/\S*)?   # 192.168.2.39:7346/x
  | (?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+       # bare host: reddit.com, nzherald.co.nz, bit.ly/x
      (?:{TLDS}|(?!(?:{NOT_TLDS})(?![\w-]))[a-z]{{2}})(?![\w-])
""", re.IGNORECASE | re.VERBOSE)


def normalize_url(url: str) -> str:
    """feed:// and rss:// links are plain https feeds. without a scheme: http:// for localhost and IPs, https:// else"""
    url = re.sub(r"^(?:feed|rss)://", "https://", url, flags=re.IGNORECASE)
    if not re.match(r"[a-z][a-z0-9+.-]*://", url, flags=re.IGNORECASE):
        local = re.match(r"(?:localhost|\d{1,3}(?:\.\d{1,3}){3})(?![\w.-])", url, flags=re.IGNORECASE)
        url = ("http://" if local else "https://") + url
    return url


class FetchUrlTool(WebsearchTool):
    """subclass of WebsearchTool only to reuse _extract_page and _get_org_name, everything else is its own"""
    description = prompts.FETCH_URL_DESCRIPTION
    requires = ()       # always there: a link in the LAN (NOMAD, a NAS) works without the internet
    requires_any = ()
    text_only = True    # no laya question: a link in the message selects it (text_score)
    PAGE_TIMEOUT = 20           # one page the user is waiting for, not a batch
    BROWSER_FALLBACK = True     # the user asked for this page, worth a headless browser if plain http comes back thin

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "fetch_url"

    @classmethod
    def text_score(cls, prompt: str) -> float:
        """1.0: the message holds a link (URL_PATTERN), fetch_url is mandatory"""
        return 1.0 if URL_PATTERN.search(prompt or "") else 0.0

    def execute(self) -> None:
        if not "url" in self.tool_call:
            logger.error("invalid fetch_url")
            return None

        url = normalize_url(str(self.tool_call["url"]).strip())
        focus = self.tool_call.get("focus") or None
        MessageQueue().send_status_message("reading the page")

        try:
            self._check(url)
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
            self.add_result({"tool": self.name(), "error": str(e)})
        except Exception as e:
            logger.error(f"failed to fetch {url} {repr(e)}")

    def _check(self, url: str) -> None:
        """raises FetchBlocked when url may not be fetched (url_check) or needs the internet while it is not there
        (also simulated): only a host in the LAN or on this machine is fetched then"""
        online = self.infrastructure is None or self.infrastructure.available("internet")
        try:
            parsed, _, ips = check_url(url)
        except FetchBlocked as e:
            if not online and str(e).startswith("can't resolve"):
                raise FetchBlocked(prompts.FETCH_URL_OFFLINE_PART.format(url=url))
            raise
        if not online and not is_local_host(parsed.hostname, ips):
            raise FetchBlocked(prompts.FETCH_URL_OFFLINE_PART.format(url=url))

    @classmethod
    def prompt(cls) -> str:
        return prompts.FETCH_URL_PROMPT
