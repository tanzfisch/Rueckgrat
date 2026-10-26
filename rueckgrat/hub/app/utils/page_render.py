import threading
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

from app.common import get_logger
from app.utils.url_check import is_public_http_url
logger = get_logger()

# headless chromium for pages that only fill in with javascript (spa news sites) or block plain http clients.
# optional: playwright comes with the INSTALL_BROWSER build arg of the hub image, without it render_page returns None

RENDER_TIMEOUT = 15     # seconds for one page, launch to html
MAX_BROWSERS = 2        # a chromium takes ~200 MB, don't let a burst of tool calls start many
SKIP_RESOURCES = {"image", "media", "font"}
# true once the page has some text and its length didn't change for 2.5 s (stuff pauses ~1 s between its api calls)
SETTLED_JS = """() => {
    const n = document.body ? document.body.innerText.length : 0;
    if (n !== window.__rgLen) { window.__rgLen = n; window.__rgSince = Date.now(); }
    return n > 500 && Date.now() - window.__rgSince > 2500;
}"""

_slots = threading.Semaphore(MAX_BROWSERS)
_missing_logged = False


def render_page(url: str, user_agent: str, timeout: float = RENDER_TIMEOUT) -> Optional[Tuple[str, str]]:
    """loads url in headless chromium and returns (final url, rendered html) or None"""
    global _missing_logged
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError:
        if not _missing_logged:
            logger.warning("playwright not installed (hub built without INSTALL_BROWSER), no browser fallback")
            _missing_logged = True
        return None

    deadline = time.monotonic() + timeout
    remaining_ms = lambda: max(1, int((deadline - time.monotonic()) * 1000))
    public_hosts = {}

    def route(r):
        # the page's own requests get the same SSRF check as the url, and skip what we don't read
        host = urlparse(r.request.url).hostname
        if host not in public_hosts:
            public_hosts[host] = r.request.url.startswith(("http://", "https://")) and is_public_http_url(r.request.url)
        if not public_hosts[host] or r.request.resource_type in SKIP_RESOURCES:
            r.abort()
        else:
            r.continue_()

    if not _slots.acquire(timeout=timeout):
        logger.warning(f"no free browser to render {url}")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--disable-dev-shm-usage"], timeout=remaining_ms())
            try:
                page = browser.new_page(user_agent=user_agent)
                page.route("**/*", route)
                page.goto(url, wait_until="domcontentloaded", timeout=remaining_ms())
                try:
                    # done when the text stopped growing. not networkidle: live pages keep polling and never go idle
                    page.wait_for_function(SETTLED_JS, polling=500, timeout=max(1, remaining_ms() - 1000))
                except PlaywrightError:
                    pass    # take what is there at the deadline
                return page.url, page.content()
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"browser failed to render {url}: {repr(e)}")
        return None
    finally:
        _slots.release()
