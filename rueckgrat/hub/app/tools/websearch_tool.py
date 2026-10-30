from typing import Dict, Any, Optional
import re
import json
from .tool import Tool, ToolCategory
from app.jobs.find_answer_job import FindAnswerJob
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
import tldextract
from bs4 import BeautifulSoup
from ddgs import DDGS
from app.utils.content_filter import strip_text_noise
from app.utils.page_render import render_page
from app.utils.url_check import is_public_http_url, fetch, FetchBlocked

from app.common import get_logger, MessageQueue
logger = get_logger()

class WebsearchTool(Tool):
    category = ToolCategory.WEB
    description = "searches the web for current, factual or local information (news, events, prices, stocks, opening hours)"
    question = "Does the user want current information from the web?"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str: 
        return "websearch"
    
    def _keep_content_lines(self, text):
        # sentences, headlines and live blog posts have 4+ words, times, scores and prices have digits. menu items have neither
        return '\n'.join(line for line in text.splitlines() if len(line.split()) >= 4 or re.search(r'\d', line))

    def _get_org_name(self, url: str) -> str:
        ext = tldextract.extract(url)
        domain = f"{ext.domain}.{ext.suffix}"
        org_map = {
            "google.com": "Google",
            "microsoft.com": "Microsoft",
            "apple.com": "Apple",
            "github.com": "GitHub",
            "amazon.com": "Amazon",
            "facebook.com": "Meta",
            "meta.com": "Meta",
            "twitter.com": "X",
            "x.com": "X",
            "instagram.com": "Meta",
            "linkedin.com": "LinkedIn",
            "oracle.com": "Oracle",
            "ibm.com": "IBM",
            "intel.com": "Intel",
            "amd.com": "AMD",
            "nvidia.com": "NVIDIA",
            "adobe.com": "Adobe",
            "salesforce.com": "Salesforce",
            "sap.com": "SAP",
            "cisco.com": "Cisco",
            "walmart.com": "Walmart",
            "exxonmobil.com": "ExxonMobil",
            "gm.com": "General Motors",
            "ford.com": "Ford",
            "unitedhealth.com": "UnitedHealth Group",
            "cvshealth.com": "CVS Health",
            "berkshirehathaway.com": "Berkshire Hathaway",
            "alphabet.com": "Alphabet",
            "mckesson.com": "McKesson",
            "chevron.com": "Chevron",
            "costco.com": "Costco",
            "jpmorganchase.com": "JPMorgan Chase",
            "home depot.com": "Home Depot",  # Note: adjust key if needed
            "walgreensbootsalliance.com": "Walgreens",
            "target.com": "Target",
            "tesla.com": "Tesla",
            "bankofamerica.com": "Bank of America",
            "wellsfargo.com": "Wells Fargo",
            "verizon.com": "Verizon",
            "atandt.com": "AT&T",
            "comcast.com": "Comcast",
            "pepsico.com": "PepsiCo",
            "pfizer.com": "Pfizer",
            "abbott.com": "Abbott",
            "johnsonandjohnson.com": "Johnson & Johnson",
            "procterandgamble.com": "Procter & Gamble",
            "cocacola.com": "Coca-Cola",
            "nytimes.com": "New York Times",
            "cnn.com": "CNN",
            "bbc.com": "BBC",
            "foxnews.com": "Fox News",
            "reuters.com": "Reuters",
            "apnews.com": "AP News",
            "theguardian.com": "The Guardian",
            "washingtonpost.com": "Washington Post",
            "wsj.com": "Wall Street Journal",
            "bloomberg.com": "Bloomberg",
            "news.ycombinator.com": "Hacker News",
            "dev.to": "DEV Community",
            "stackoverflow.com": "Stack Overflow",
            "github.com": "GitHub",
            "techcrunch.com": "TechCrunch",
            "arstechnica.com": "Ars Technica",
            "dzone.com": "DZone",
            "slashdot.org": "Slashdot",
            "infoq.com": "InfoQ",
            "medium.com": "Medium",
            "gamedeveloper.com": "Game Developer",
            "gamefromscratch.com": "GameFromScratch",
            "gamedev.net": "GameDev.net",
            "gamesindustry.biz": "GamesIndustry.biz",
            "kotaku.com": "Kotaku",
            "polygon.com": "Polygon",
            "ign.com": "IGN",
            "unity.com": "Unity",
            "unrealengine.com": "Unreal Engine",
            "yahoo.com": "Yahoo News",
            "msn.com": "MSN",
            "forbes.com": "Forbes",
            "usatoday.com": "USA Today",
            "espn.com": "ESPN",
            "nbcnews.com": "NBC News",
            "aljazeera.com": "Al Jazeera",
            "theatlantic.com": "The Atlantic",
            "daily.dev": "daily.dev",
            "freecodecamp.org": "freeCodeCamp",
            "sdtimes.com": "SD Times",
            "hackernews.com": "Hacker News",  # alias
            "reddit.com": "Reddit",
            "engineering.fb.com": "Meta Engineering",
            "netflixtechblog.com": "Netflix Tech Blog",
            "gameinformer.com": "Game Informer",
            "newzoo.com": "Newzoo",
            "appdevelopermagazine.com": "App Developer Magazine",
            "weather.com": "The Weather Channel",
            "accuweather.com": "AccuWeather",
            "wunderground.com": "Weather Underground",
            "weather.gov": "National Weather Service",
            "noaa.gov": "NOAA",
            "metoffice.gov.uk": "UK Met Office",
            "yr.no": "YR",
            "metservice.com": "MetService",
            "weatherwatch.co.nz": "WeatherWatch",
            "weather.niwa.co.nz": "NIWA Weather",
            "metvuw.com": "MetVUW",
            "stuff.co.nz": "Stuff",
            "nzherald.co.nz": "NZ Herald",
            "rnz.co.nz": "RNZ",
            "1news.co.nz": "1News",
            "tvnz.co.nz": "TVNZ",
            "newsroom.co.nz": "Newsroom",
            "thespinoff.co.nz": "The Spinoff",
            "spiegel.de": "Der Spiegel",
            "zeit.de": "Die Zeit",
            "faz.net": "FAZ",
            "sueddeutsche.de": "Süddeutsche Zeitung",
            "bild.de": "Bild",
            "tagesschau.de": "Tagesschau",
            "dw.com": "Deutsche Welle",
            "rt.com": "Russia Today",
            "apolut.net": "Apolut",
            "nachdenkseiten.de": "NachDenkSeiten"
        }

        return org_map.get(domain, domain)

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    PAGE_TIMEOUT = 8            # seconds per page, the pages of a batch load in parallel
    BROWSER_FALLBACK = False    # websearch falls back to the search snippet, it can't wait for a browser per result
    MIN_PAGE_CHARS = 200        # less text than this is not worth reading
    THIN_PAGE_CHARS = 500       # less than this from plain http looks like a javascript page, try the browser
    BLOCKED_STATUS = {401, 403, 429, 503}   # bot walls, a real browser often gets through
    OVERLAY = re.compile(r"cookie|consent|gdpr|paywall|banner|modal|popup|overlay", re.IGNORECASE)
    OVERLAY_MAX_WORDS = 80      # only short overlays go, a "hero-banner" holding the lead paragraph stays
    CHALLENGE = re.compile(r"not a (ro)?bot|checking your browser|just a moment|enable javascript and cookies|"
                           r"verify you are human|access denied", re.IGNORECASE)   # bot wall pages, not content

    def _is_overlay(self, elem) -> bool:
        attrs = " ".join(elem.get("class") or []) + " " + (elem.get("id") or "")
        return bool(self.OVERLAY.search(attrs)) and len(elem.get_text(" ", strip=True).split()) < self.OVERLAY_MAX_WORDS

    def _structured_text(self, soup) -> str:
        """text a page carries for search engines: json-ld articleBody (also of live blog updates), else og:description"""
        bodies = []
        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("articleBody"), str):
                    bodies.append(node["articleBody"].strip())
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                walk(json.loads(script.string or ""))
            except ValueError:
                continue
        if bodies:
            return "\n".join(bodies)
        meta = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        return (meta.get("content") or "").strip() if meta else ""

    def _parse_html(self, html, url) -> Dict[str, Any]:
        """text, images and url of one page. html as bytes lets bs4 find the charset (meta tag or detection)
        instead of requests' latin-1 guess when the server sends none"""
        soup = BeautifulSoup(html, 'html.parser')
        structured = self._structured_text(soup)

        for tag in soup(["script", "style", "noscript", "iframe", "nav", "header", "footer", "aside", "form", "button", "svg"]):
            tag.decompose()
        # collect first, decompose after: decomposing while find_all walks the tree would visit dead children
        overlays = [elem for elem in soup.find_all(['div', 'section']) if self._is_overlay(elem)]
        for elem in overlays:
            if not elem.decomposed:
                elem.decompose()

        text = self._keep_content_lines(strip_text_noise(soup.get_text(separator='\n', strip=True)))
        if len(structured) > len(text):
            text = structured

        images = [img.get('src') or img.get('data-src') or img.get('data-original')
                for img in soup.find_all('img') if img.get('src') or img.get('data-src')]
        return {"text": text, "images": images, "url": url}

    def _http_get(self, url):
        # pinned to the checked address, redirects checked hop by hop (url_check). raises FetchBlocked
        resp = fetch(url, headers=self.HEADERS, timeout=self.PAGE_TIMEOUT)

        # Handle JS/meta redirect pages
        if len(resp.text.strip()) < 500 and ('location.replace' in resp.text or 'http-equiv="refresh"' in resp.text):
            match = re.search(r'location\.replace\("([^"]+)"\)', resp.text) or \
                    re.search(r'URL=([^"]+)', resp.text)
            if match:
                redirect_url = match.group(1)
                if not redirect_url.startswith('http'):
                    redirect_url = 'https://' + redirect_url.lstrip('/')
                logger.debug(f"following redirect to {redirect_url}")
                resp = fetch(redirect_url, headers=self.HEADERS, timeout=self.PAGE_TIMEOUT)
        return resp

    def _extract_page(self, url) -> Optional[Dict[str, Any]]:
        """reads one page: plain http first, the headless browser (if BROWSER_FALLBACK) when that is blocked
        or comes back too thin. returns {"text", "images", "url"} or None"""
        logger.debug(f"extract from page {url}")
        page, try_browser = None, False
        self.blocked_reason = None
        try:
            resp = self._http_get(url)
            if resp.status_code in self.BLOCKED_STATUS:
                logger.debug(f"{url} answered {resp.status_code}")
                try_browser = True
            else:
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "").lower()
                if content_type and "html" not in content_type and "xml" not in content_type:
                    logger.warning(f"not reading {url}, it is {content_type}")
                    return None
                page = self._parse_html(resp.content, resp.url)
                try_browser = len(page["text"]) < self.THIN_PAGE_CHARS
        except FetchBlocked as e:
            self.blocked_reason = str(e)    # logged at debug by url_check, fetch_url shows it
            return None
        except Exception as e:
            logger.error(f"failed to extract {url}: {repr(e)}")

        if try_browser and self.BROWSER_FALLBACK:
            rendered = render_page(url, self.HEADERS["User-Agent"])
            if rendered and is_public_http_url(rendered[0]):
                rendered_page = self._parse_html(rendered[1], rendered[0])
                logger.debug(f"browser got {len(rendered_page['text'])} characters from {url}")
                if not page or len(rendered_page["text"]) > len(page["text"]):
                    page = rendered_page

        if not page or len(page["text"]) < self.MIN_PAGE_CHARS:
            logger.warning(f"was not able to get text from {url}")
            return None
        if len(page["text"]) < self.THIN_PAGE_CHARS * 2 and self.CHALLENGE.search(page["text"]):
            logger.warning(f"{url} is behind a bot wall")
            return None
        return page

    # all ddgs 9.16.0 text engines, best first (results of higher engines come first). every engine runs in its
    # own thread with its own try/except: ddgs' own multi-backend search drops good results when another engine
    # fails first (ddgs issue #427)
    # (backend, attempts)   status measured from this network on 2026-10-17
    SEARCH_BACKENDS = [
        ("yahoo", 3),       # works, ~7 results, but empty in ~40% of calls -> retries
        ("duckduckgo", 1),  # mostly blocked (HTTP 202 bot challenge), 10 results when it gets through
        ("wikipedia", 1),   # 1 article, only for single-topic queries
        ("grokipedia", 1),  # 1 article, only for single-topic queries
        ("startpage", 1),   # HTTP 200 but no results
        ("mojeek", 1),      # HTTP 200 but no results
        ("brave", 1),       # blocked (HTTP 429)
        ("google", 1),      # blocked (HTTP 403)
    ]
    SEARCH_DEADLINE = 20  # seconds for the whole search, all engines and retries together

    def _search_engine(self, backend, attempts, query, max_results, deadline):
        """runs in a worker thread, returns the engine's hits or [] (never raises)"""
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining < 1:
                break
            try:
                return DDGS(timeout=min(10, int(remaining))).text(query, max_results=max_results, backend=backend)
            except Exception as e:
                logger.warning(f"websearch {backend} attempt {attempt}/{attempts} failed {repr(e)}")
                if attempt < attempts:
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
        return []

    def _web_search(self, query, num_results):
        logger.debug(f"search query: {query}")
        deadline = time.monotonic() + self.SEARCH_DEADLINE
        hits_by_backend = {}

        def merged():
            # dedupe by url, results of higher ranked engines first
            results, seen, contributed = [], set(), []
            for backend, _ in self.SEARCH_BACKENDS:
                added = 0
                for hit in hits_by_backend.get(backend, []):
                    url = hit.get("href") or ""
                    if url and url not in seen and len(results) < num_results:
                        seen.add(url)
                        results.append({
                            'title': hit.get("title", ""),
                            'url': url,
                            'snippet': hit.get("body", "")
                        })
                        added += 1
                if added:
                    contributed.append(f"{backend}:{added}")
            return results, contributed

        executor = ThreadPoolExecutor(max_workers=len(self.SEARCH_BACKENDS), thread_name_prefix="websearch")
        futures = {
            executor.submit(self._search_engine, backend, attempts, query, num_results * 2, deadline): backend  # extra buffer
            for backend, attempts in self.SEARCH_BACKENDS
        }
        try:
            for future in as_completed(futures, timeout=max(0, deadline - time.monotonic())):
                try:
                    hits_by_backend[futures[future]] = future.result()
                except Exception as e:
                    logger.warning(f"websearch {futures[future]} failed {repr(e)}")
                if len(merged()[0]) >= num_results:
                    break
        except FuturesTimeoutError:
            logger.warning(f"websearch deadline of {self.SEARCH_DEADLINE}s reached")
        finally:
            # don't wait for stragglers, their ddgs timeout ends them in the background
            executor.shutdown(wait=False, cancel_futures=True)

        results, contributed = merged()
        if results:
            logger.debug(f"websearch got {len(results)} results from {', '.join(contributed)}")
        else:
            logger.error(f"failed websearch, no engine gave results for {query}")
        return results

    def execute(self) -> None:
        try:
            if not "query" in self.tool_call:
                logger.error("invalid websearch")
                return None
            
            MessageQueue().send_status_message(f"searching the web")
            
            query = self.tool_call["query"]
            search_results = self._web_search(query, 10)
            jobs = []
            good_results = []
            seen_urls = set()
            i = 0
            threshold = 5
            target = 3

            while i < len(search_results) and len(good_results) < target:
                batch = search_results[i:i+5]
                i += len(batch)
                
                # the pages of a batch load in parallel, a slow site only costs its own timeout
                with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="extract") as pool:
                    extractions = list(pool.map(self._extract_page, [result["url"] for result in batch]))

                batch_jobs = []
                for result, extraction in zip(batch, extractions):
                    if extraction:
                        result["url"] = extraction["url"]
                        information = extraction["text"]
                    elif result["snippet"]:
                        # page not readable (javascript, paywall, bot wall), the engine's snippet often has the answer
                        information = f"{result['title']}\n{result['snippet']}"
                    else:
                        continue

                    if result["url"] in seen_urls:
                        continue
                    seen_urls.add(result["url"])

                    job = FindAnswerJob(question=query, information=information, infrastructure=self.infrastructure)
                    self.add_sub_job(job)
                    batch_jobs.append((result, job))
                    jobs.append((result, job))

                if batch_jobs:
                    self.wait_for([j[1] for j in batch_jobs])
                
                for result, job in batch_jobs:
                    url = result["url"]
                    source = self._get_org_name(url)
                    title = result["title"]

                    answer = job.result()
                    if not answer:
                        logger.debug(f"no answer for {url}")
                        continue
                    if answer["quality"] > threshold:
                        good_results.append({ 
                            "answer": answer['answer'], 
                            "answer_quality": answer['quality'],
                            "source": source,
                            "title": title,
                            "url": url,
                        })
                        self.add_source(url, title)
                        if len(good_results) >= target:
                            break
                    else:
                        logger.debug(f"missed threshold: {answer['answer']} at {answer['quality']}")

            if good_results:
                self.response["websearch_results"] = sorted(good_results, key=lambda x: x["answer_quality"], reverse=True)    # best first
            else:
                logger.error("web search failed. found no results")
                self.response["websearch_results"] = []

        except Exception as e:
            logger.error(f"failed to do a websearch {repr(e)}")

    @classmethod
    def prompt(cls) -> str:
        return """
WEBSEARCH:
Use for current, factual, real-time, or location-specific information, or when you need fresh ideas.

Parameters:
- query (string, required): the search query

Example:
{"tool": "websearch", "query": "current NZD to USD exchange rate"}
"""
