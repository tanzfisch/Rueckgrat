from typing import Dict,  Any
import re
from .tool import Tool
from app.jobs.find_answer_job import FindAnswerJob
from app.utils.message_queue import MessageQueue
import requests
import datetime
import tldextract
from bs4 import BeautifulSoup

from app.common import Logger
logger = Logger(__name__).get_logger()

class WebsearchTool(Tool):
    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str: 
        return "websearch"
    
    def _remove_short_lines(self, text):
        return '\n'.join(line for line in text.splitlines() if len(line.split()) >= 10)    
    
    def _remove_non_sentence_lines(self, text):
        text = self._remove_short_lines(text)
        return '\n'.join(line for line in text.splitlines() if re.search(r'[.!?]', line.strip()))    
    
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

    def _extract_page(self, url) -> str:
        resulting_url = url
        logger.debug(f"extract from page {url}")        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            resp.raise_for_status()

            # Handle JS/meta redirect pages
            if len(resp.text.strip()) < 500 and ('location.replace' in resp.text or 'http-equiv="refresh"' in resp.text):
                import re
                match = re.search(r'location\.replace\("([^"]+)"\)', resp.text) or \
                        re.search(r'URL=([^"]+)', resp.text)
                if match:
                    redirect_url = match.group(1)
                    if not redirect_url.startswith('http'):
                        redirect_url = 'https://' + redirect_url.lstrip('/')
                    logger.debug(f"following redirect to {redirect_url}")
                    resp = requests.get(redirect_url, headers=headers, timeout=20, allow_redirects=True)
                    resulting_url = redirect_url
                    resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Stronger cleanup
            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "button", "svg"]):
                tag.decompose()
            
            # Remove common paywall / cookie banners
            for elem in soup.find_all(['div', 'section'], class_=lambda x: x and any(c in str(x).lower() for c in ['cookie', 'banner', 'paywall', 'modal'])):
                elem.decompose()
            
            text = self._remove_non_sentence_lines(soup.get_text(separator='\n', strip=True))

            logger.debug(f"text found on page {text}")
            
            if len(text.strip()) < 200:
                return None  # still too empty (JS-heavy page)
                
            images = [img.get('src') or img.get('data-src') or img.get('data-original') 
                    for img in soup.find_all('img') if img.get('src') or img.get('data-src')]
            
            return {"text": text, "images": images, "url": resulting_url}
        except Exception as e:
            logger.error(f"failed to extract {url}: {repr(e)}")
            return None

    def _improve_search_query(self, query):
        improvements = [
            " -inurl:(/world/ /topic/ /section/ /tag/ /category/)",
            f" after:{datetime.datetime.now().year - 2}",
        ]
        return query + " " + " ".join(improvements)

    def _web_search(self, query, num_results):
        try:
            url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            logger.debug(f"search query: {url}")
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers)
            soup = BeautifulSoup(resp.text, 'html.parser')
            results = []
            seen = set()
            for g in soup.select('.result')[:num_results * 2]:  # extra buffer
                title = g.select_one('.result__title')
                link = g.select_one('.result__url')
                snippet = g.select_one('.result__snippet')
                if title and link:
                    url = 'https:' + link.get('href') if link.get('href', '').startswith('//') else link.get('href') or ''
                    if url and url not in seen:
                        seen.add(url)
                        results.append({
                            'title': title.get_text(strip=True),
                            'url': url,
                            'snippet': snippet.get_text(strip=True) if snippet else ''                        
                        })
                        if len(results) >= num_results:
                            break
            return results
        except Exception as e:
            logger.error(f"failed websearch {repr(e)}")

        return None

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
                
                batch_jobs = []
                for result in batch:
                    url = result["url"]
                    extraction = self._extract_page(url)
                    if not extraction:
                        continue

                    actual_url = extraction["url"]
                    if actual_url in seen_urls:
                        continue
                    seen_urls.add(actual_url)

                    result["url"] = actual_url

                    job = FindAnswerJob(question=query, information=extraction["text"], infrastructure=self.infrastructure)
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
                    if answer["quality"] > threshold:
                        good_results.append({ 
                            "answer": answer['answer'], 
                            "answer_quality": answer['quality'],
                            "source": source,
                            "title": title,
                            "url": url,
                        })
                        MessageQueue().send_url(url)
                        if len(good_results) >= target:
                            break
                    else:
                        logger.debug(f"missed threshold: {answer['answer']} at {answer['quality']}")

            if good_results:
                self.response["websearch_results"] = sorted(good_results, key=lambda x: x["answer_quality"])  
            else:
                logger.error("web search failed. found no results")
                self.response["websearch_results"] = []

        except Exception as e:
            logger.error(f"failed to do a websearch {repr(e)}")

    @classmethod
    def prompt(cls) -> str: 
        return """
WEBSEARCH:

Use the websearch tool for any precise, factual, current, latest, real-time, location-specific, or dynamic information (e.g. weather, prices, currencies, crypto, stocks, events, stats, news). If so, include:
{
  "tool": "websearch",
  "query": "exact search query"
}
"""
