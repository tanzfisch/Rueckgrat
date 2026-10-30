import threading
import time
from typing import Optional, Tuple

from app.common import get_logger
from app.utils.url_check import fetch, FetchBlocked
logger = get_logger()

# headless chromium for pages that only fill in with javascript (spa news sites) or block plain http clients.
# playwright is always in the hub image. without it (e.g. a local run) render_page returns None

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
            logger.warning("playwright not installed, no browser fallback")
            _missing_logged = True
        return None

    deadline = time.monotonic() + timeout
    remaining_ms = lambda: max(1, int((deadline - time.monotonic()) * 1000))

    def route(r):
        # chromium never goes to the network itself: every request of the page is fetched here, with the same
        # SSRF check and pinning as plain http (url_check). redirects go back to chromium, which asks again for
        # the new url, so every hop is checked. what we don't read is skipped
        req = r.request
        if req.resource_type in SKIP_RESOURCES or not req.url.startswith(("http://", "https://")):
            r.abort()
            return
        try:
            try:
                headers = req.all_headers()     # incl. cookies
            except Exception:
                headers = req.headers
            resp = fetch(req.url, headers=headers, method=req.method, body=req.post_data_buffer,
                         timeout=max(1.0, deadline - time.monotonic()), follow_redirects=False)
        except FetchBlocked:
            r.abort("blockedbyclient")
            return
        except Exception as e:
            logger.debug(f"browser request {req.url} failed: {repr(e)}")
            r.abort()
            return
        # the body is already decoded and complete
        drop = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        r.fulfill(status=resp.status_code, headers={k: v for k, v in resp.headers.items() if k.lower() not in drop}, body=resp.content)

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
