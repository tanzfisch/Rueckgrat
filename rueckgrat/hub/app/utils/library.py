"""
The offline library: a kiwix-serve (Project NOMAD's Information Library) with its ZIM books (Wikipedia, Q&A sites,
manuals ...). Read only GETs, used when the internet is not there (or an online lookup fails):
  /catalog/v2/entries?count=-1          the books (atom xml)
  /search?books.name=A&books.name=B&pattern=...&format=xml&pageLength=n   full text search, books of ONE language only
  /suggest?content=<book>&term=...      title suggestions of one book (json)
  /raw/<book>/content/<path>            an article's html
A book is addressed by its id, the last part of its /content/<id> link (e.g. wikipedia_en_top_nopic_2026-06), not by its name.
The hub keeps no book list: the catalog is read when it is needed (one request per search or lookup), kiwix-serve has it at hand.
"""
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

import requests
from bs4 import BeautifulSoup

from app.common import get_logger
logger = get_logger()

LIBRARY_TIMEOUT = 15            # seconds per request, a search over many books takes a few
ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
# the 2 letter codes the tools get -> the ISO 639-3 codes of the catalog
LANGUAGES = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "nl": "nld", "ru": "rus",
             "pl": "pol", "sv": "swe", "da": "dan", "no": "nor", "fi": "fin", "ja": "jpn", "zh": "zho", "ko": "kor",
             "ar": "ara", "tr": "tur", "he": "heb", "hi": "hin", "el": "ell", "cs": "ces", "hu": "hun", "ro": "ron",
             "uk": "ukr", "vi": "vie", "id": "ind", "fa": "fas", "th": "tha", "mi": "mri"}
DROPPED = ("script", "style", "noscript", "table", "sup", "figure", "nav", "footer", "header")
DROPPED_CLASSES = re.compile(r"^(?:infobox.*|navbox.*|reference.*|mw-editsection|metadata|hatnote|toc|thumb.*|reflist|sidebar.*|noprint)$")


class LibraryError(Exception):
    """the library is not reachable or answered with an error, the message is for the log and the model"""


def language_code(lang: str) -> str:
    """"en" -> "eng", a 3 letter code stays, unknown: "eng" """
    lang = str(lang or "").strip().lower()
    if len(lang) == 3 and lang.isalpha():
        return lang
    return LANGUAGES.get(lang, "eng")


class Library:
    """one kiwix-serve, its books are read from its catalog on each use. http_get: requests.get or a fake with the same signature"""

    def __init__(self, base_url: str, http_get: Callable = requests.get):
        self._base = base_url.rstrip("/")
        self._get = http_get

    def base_url(self) -> str:
        return self._base

    def answers(self, timeout: float) -> bool:
        """the catalog answers with at least one book (one entry asked for, the capability probe)"""
        try:
            resp = self._get(f"{self._base}/catalog/v2/entries", params={"count": "1"}, timeout=timeout)
            return resp.status_code == 200 and ET.fromstring(resp.content).find(f"{ATOM}entry") is not None
        except Exception as e:
            logger.debug(f"library {self._base}: {e!r}")
            return False

    def books(self) -> List[Dict[str, Any]]:
        """the books right now, [{"id", "name", "title", "language", "articles"}] without the duplicates (catalog_books).
        raises LibraryError"""
        return self.catalog_books(self._request("/catalog/v2/entries", {"count": "-1"}).content)

    def content_url(self, book_id: str, path: str) -> str:
        """the page for people, the source link of a result"""
        return f"{self._base}/content/{quote(book_id)}/{quote(path, safe='/')}"

    # ---------------------------------------------------------------- catalog
    @staticmethod
    def catalog_books(xml_text) -> List[Dict[str, Any]]:
        """the books of /catalog/v2/entries. one book in several copies (maxi and nopic of the same name): the one with
        the most articles. raises LibraryError for xml that is no catalog"""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise LibraryError(f"library catalog not readable ({e})")
        books: Dict[str, Dict[str, Any]] = {}
        for entry in root.findall(f"{ATOM}entry"):
            link = next((l.get("href", "") for l in entry.findall(f"{ATOM}link") if l.get("type") == "text/html"), "")
            book_id = link.rstrip("/").rsplit("/", 1)[-1] if link else ""
            if not book_id:
                continue
            try:
                articles = int(entry.findtext(f"{ATOM}articleCount") or 0)
            except ValueError:
                articles = 0
            book = {"id": book_id, "name": entry.findtext(f"{ATOM}name") or book_id, "title": entry.findtext(f"{ATOM}title") or book_id,
                    "language": (entry.findtext(f"{ATOM}language") or "").strip(), "articles": articles}
            known = books.get(book["name"])
            if known is None or book["articles"] > known["articles"]:
                books[book["name"]] = book
        return list(books.values())

    def wikipedia_book(self, lang: str = "en") -> Optional[Dict[str, Any]]:
        """the biggest Wikipedia book in lang (2 or 3 letter code), else the biggest in any language, None without one.
        raises LibraryError"""
        wikis = [b for b in self.books() if b["name"].startswith("wikipedia_")]
        code = language_code(lang)
        own = [b for b in wikis if b["language"] == code]
        pool = own or wikis
        return max(pool, key=lambda b: b["articles"]) if pool else None

    @staticmethod
    def language_groups(books: List[Dict[str, Any]], lang: str = "en") -> List[List[Dict[str, Any]]]:
        """books (books()) by language, kiwix searches only books of one language together: the books of lang alone when
        it has any, else every group (a book with several languages is a group of its own)"""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for book in books:
            groups.setdefault(book["language"], []).append(book)
        code = language_code(lang)
        if code in groups:
            return [groups[code]]
        return list(groups.values())

    # ---------------------------------------------------------------- requests
    def _request(self, path: str, params=None) -> requests.Response:
        try:
            resp = self._get(f"{self._base}{path}", params=params, timeout=LIBRARY_TIMEOUT)
        except Exception as e:
            raise LibraryError(f"offline library unreachable ({type(e).__name__})")
        if resp.status_code != 200:
            raise LibraryError(f"offline library answered {resp.status_code}")
        return resp

    def search(self, query: str, lang: str = "en", count: int = 10) -> List[Dict[str, Any]]:
        """full text search over the books of lang (language_groups), [{"title", "book_id", "book", "path", "url"}], the
        best first per group, one hit per title. a group that fails is logged and skipped. raises LibraryError when the
        catalog does not answer"""
        hits, seen = [], set()
        for group in self.language_groups(self.books(), lang):
            params = [("pattern", query), ("format", "xml"), ("pageLength", str(count))] + [("books.name", b["id"]) for b in group]
            try:
                root = ET.fromstring(self._request("/search", params).content)
            except (LibraryError, ET.ParseError) as e:
                logger.warning(f"library search {query!r} in {len(group)} book(s) failed: {e}")
                continue
            titles = {b["id"]: b["title"] for b in group}
            for item in root.iter("item"):
                link = item.findtext("link") or ""
                match = re.match(r"/content/([^/]+)/(.+)", link)
                title = " ".join((item.findtext("title") or "").split())
                if not match or not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                book_id, path = unquote(match.group(1)), unquote(match.group(2))     # the link is url encoded, a path is not
                book = (item.find("book").findtext("title") if item.find("book") is not None else None) or titles.get(book_id, book_id)
                hits.append({"title": title, "book_id": book_id, "book": book, "path": path, "url": self.content_url(book_id, path)})
        return hits

    def suggest(self, book_id: str, term: str, count: int = 5) -> List[Dict[str, str]]:
        """the titles of book_id that start like term, [{"title", "path"}]"""
        try:
            data = json.loads(self._request("/suggest", {"content": book_id, "term": term, "count": str(count)}).content)
        except ValueError:
            return []
        return [{"title": str(s.get("value", "")).strip(), "path": s["path"]} for s in data
                if isinstance(s, dict) and s.get("kind") == "path" and s.get("path")]

    def article(self, book_id: str, path: str) -> str:
        """the html of one article"""
        resp = self._request(f"/raw/{quote(book_id)}/content/{quote(path, safe='/')}")
        return resp.content.decode("utf-8", errors="replace")     # kiwix-serve sends no charset, requests would read latin-1

    def lookup(self, book_id: str, query: str) -> Optional[Dict[str, str]]:
        """the article of book_id about query: a title that is query (suggest), else the best full text hit in the book,
        else the first suggestion. {"title", "path", "html", "url"} or None"""
        suggestions = self.suggest(book_id, query)
        wanted = " ".join(query.split()).lower()
        best = next((s for s in suggestions if s["title"].lower() == wanted), None)
        if best is None:
            params = [("pattern", query), ("format", "xml"), ("pageLength", "1"), ("books.name", book_id)]
            try:
                item = next(ET.fromstring(self._request("/search", params).content).iter("item"), None)
            except ET.ParseError:
                item = None
            match = re.match(r"/content/[^/]+/(.+)", item.findtext("link") or "") if item is not None else None
            if match:
                best = {"title": " ".join((item.findtext("title") or "").split()), "path": unquote(match.group(1))}
        if best is None and suggestions:
            best = suggestions[0]
        if best is None:
            return None
        return {**best, "html": self.article(book_id, best["path"]), "url": self.content_url(book_id, best["path"])}

    # ---------------------------------------------------------------- html
    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"\[\s*(?:\d+|[a-z]|citation needed|note \d+)\s*\]", "", text)
        return " ".join(text.split())

    @classmethod
    def _content(cls, html: str):
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(DROPPED):
            tag.decompose()
        for tag in soup.find_all(class_=DROPPED_CLASSES):
            tag.decompose()
        return soup.select_one(".mw-parser-output") or soup.body or soup

    @classmethod
    def page_text(cls, html: str, max_chars: int) -> str:
        """the readable text of a page (no scripts, tables, navigation, references), at most max_chars"""
        root = cls._content(html)
        blocks = [cls._clean(el.get_text(" ")) for el in root.find_all(["h1", "h2", "h3", "p", "li", "pre", "blockquote"])]
        text = "\n".join(b for b in blocks if b) or cls._clean(root.get_text(" "))
        return text[:max_chars].rsplit(" ", 1)[0] + " ..." if len(text) > max_chars else text

    @classmethod
    def lead_text(cls, html: str, max_chars: int) -> str:
        """the paragraphs before the first section heading (an article's summary), at most max_chars"""
        paragraphs = []
        for el in cls._content(html).find_all(["p", "h2"]):
            if el.name == "h2":
                if paragraphs:
                    break
                continue
            text = cls._clean(el.get_text(" "))
            if text:
                paragraphs.append(text)
        text = "\n".join(paragraphs)
        return text[:max_chars].rsplit(" ", 1)[0] + " ..." if len(text) > max_chars else text

    @staticmethod
    def coordinates(html: str) -> Optional[Tuple[float, float, int]]:
        """(lat, lon, decimals) of an article's place: its last <span class="geo"> (an article about a country lists its
        capital first and its own coordinates at the end), decimals: the fewest decimals of the two (how exact it is)"""
        found = re.findall(r'<span class="geo">\s*(-?\d+(?:\.(\d+))?)\s*;\s*(-?\d+(?:\.(\d+))?)\s*<', html)
        if not found:
            return None
        lat, lat_dec, lon, lon_dec = found[-1]
        lat, lon = float(lat), float(lon)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon, min(len(lat_dec), len(lon_dec))
