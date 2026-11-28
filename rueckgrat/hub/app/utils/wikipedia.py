"""Wikipedia article summaries: the public REST API, or the offline library's copy when the internet is not there."""
from typing import Dict, Optional, Tuple
import re
from urllib.parse import quote, unquote

import requests

from app.utils.library import Library, LibraryError

from app.common import get_logger
logger = get_logger()

# Wikipedia's public REST API, no key. Wikimedia asks for a descriptive User-Agent
WIKIPEDIA_SEARCH_URL = "https://{lang}.wikipedia.org/w/rest.php/v1/search/title"
WIKIPEDIA_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIPEDIA_HEADERS = {"User-Agent": "Rueckgrat/1.0 (self-hosted personal assistant)", "Accept": "application/json"}
WIKIPEDIA_TIMEOUT = 10
MAX_SUMMARY_LENGTH = 1500
# lang.wikipedia.org or lang.m.wikipedia.org, then /wiki/Title
WIKIPEDIA_URL = re.compile(
    r"^https?://(?:([a-z]{2,3})\.)?(?:m\.)?wikipedia\.org/wiki/([^?#]+)(?:[?#].*)?$",
    re.IGNORECASE,
)
# not a main-namespace article (the search engines sometimes return these)
WIKIPEDIA_SKIP_PREFIXES = (
    "Special:", "Help:", "Wikipedia:", "File:", "Image:", "Talk:", "User:", "Template:",
    "Category:", "Portal:", "Draft:", "Module:", "MediaWiki:", "TimedText:", "WP:",
)


class WikipediaError(Exception):
    pass


class WikipediaUnreachable(WikipediaError):
    """Wikipedia did not answer (no internet, an error): the offline library is asked instead"""


def is_wikipedia_book(book_id: str) -> bool:
    """a kiwix Wikipedia ZIM (catalog id, e.g. wikipedia_en_top_nopic_2026-06)"""
    return str(book_id or "").startswith("wikipedia_")


def wikipedia_hit(url: str) -> Optional[Tuple[str, str]]:
    """(lang, title) of a main-namespace Wikipedia article url, else None. title is unquoted, with spaces."""
    match = WIKIPEDIA_URL.match((url or "").strip())
    if not match:
        return None
    lang = (match.group(1) or "en").lower()
    if lang == "www" or not re.fullmatch(r"[a-z]{2,3}", lang):
        return None
    # the path can include a fragment already stripped by the regex; a trailing slash or encoded slash stays in the title
    raw = match.group(2).rstrip("/")
    if not raw or "/" in raw:
        return None
    title = unquote(raw).replace("_", " ").strip()
    if not title:
        return None
    for prefix in WIKIPEDIA_SKIP_PREFIXES:
        if title.lower().startswith(prefix.lower()):
            return None
    return lang, title


def wikipedia_page_summary(title: str, lang: str = "en") -> Dict[str, str]:
    """{"title", "summary", "url"} of this article (the REST summary). title is the article name or its URL key."""
    lang = str(lang or "en").strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", lang):
        raise WikipediaError(f"invalid language code '{lang}'")
    key = quote(str(title or "").replace(" ", "_"), safe="")
    if not key:
        raise WikipediaError("no Wikipedia article title")
    try:
        resp = requests.get(WIKIPEDIA_SUMMARY_URL.format(lang=lang, title=key),
                            headers=WIKIPEDIA_HEADERS, timeout=WIKIPEDIA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except WikipediaError:
        raise
    except Exception as e:
        logger.warning(f"wikipedia request failed {repr(e)}")
        raise WikipediaUnreachable(f"Wikipedia unreachable ({type(e).__name__})")

    return _from_rest(data, title)


def wikipedia_summary(query: str, lang: str = "en") -> Dict[str, str]:
    """returns {"title", "summary", "url"} of the best matching article"""
    lang = str(lang or "en").strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", lang):
        raise WikipediaError(f"invalid language code '{lang}'")
    try:
        resp = requests.get(WIKIPEDIA_SEARCH_URL.format(lang=lang), params={"q": query, "limit": 1},
                            headers=WIKIPEDIA_HEADERS, timeout=WIKIPEDIA_TIMEOUT)
        resp.raise_for_status()
        pages = resp.json().get("pages", [])
        if not pages:
            raise WikipediaError(f"no Wikipedia article found for '{query}'")
        title_key = pages[0]["key"]
    except WikipediaError:
        raise
    except Exception as e:
        logger.warning(f"wikipedia request failed {repr(e)}")
        raise WikipediaUnreachable(f"Wikipedia unreachable ({type(e).__name__})")

    return wikipedia_page_summary(title_key, lang)


def _from_rest(data: dict, fallback_title: str) -> Dict[str, str]:
    summary = (data.get("extract") or "").strip()
    if not summary:
        raise WikipediaError(f"the article '{data.get('title', fallback_title)}' has no summary")
    if data.get("type") == "disambiguation":
        summary = "(disambiguation page, the term has several meanings) " + summary
    if len(summary) > MAX_SUMMARY_LENGTH:
        summary = summary[:MAX_SUMMARY_LENGTH].rsplit(" ", 1)[0] + " ..."
    url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
    return {"title": data.get("title", fallback_title), "summary": summary, "url": url}


def library_page_summary(library: Library, hit: Dict[str, str], html: Optional[str] = None) -> Dict[str, str]:
    """the lead of a known offline library article (hit has title, book_id, path, url, book). {"title", "summary", "url", "book"}"""
    try:
        if html is None:
            html = library.article(hit["book_id"], hit["path"])
    except LibraryError as e:
        raise WikipediaError(str(e))
    summary = Library.lead_text(html, MAX_SUMMARY_LENGTH)
    if not summary:
        raise WikipediaError(f"the article '{hit.get('title', '')}' has no summary")
    return {"title": hit["title"], "summary": summary, "url": hit["url"], "book": hit.get("book") or ""}


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
    return library_page_summary(library, {
        "title": article["title"], "book_id": book["id"], "path": article["path"],
        "url": article["url"], "book": book["title"],
    }, html=article["html"])
