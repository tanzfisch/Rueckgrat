import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin
from .websearch_tool import WebsearchTool
from . import prompts
from app.tasks.find_offer_task import FindOfferTask
from app.utils.url_check import is_public_http_url

from app.common import get_logger, MessageQueue
logger = get_logger()

MAX_QUERY_LENGTH = 200
SEARCH_SUFFIX = "price"     # added to the query, the engines find shops and price comparisons then
SEARCH_RESULTS = 10         # pages read per search
PAGE_WORKERS = 5            # pages loaded at the same time
MIN_MATCH = 6               # a find fits the request at least this well (FindOfferTask's match, 1 to 10), else it is dropped
MAX_FINDINGS = 10           # the podium's three and the list under it
PODIUM = 3
PRICE_TOLERANCE = 0.006     # a price counts as found when an amount on the page is this close to it
# an amount as pages write it: 1299, 1299.00, 1,299.00, 1.299,00, 1 299,00, 12.5
AMOUNT = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:[,.\s\u00a0\u202f']\d{3})+|\d+)(?:[.,]\d{1,2})?(?![\d])")
CURRENCIES = "NZD|AUD|USD|CAD|EUR|GBP|CHF|JPY|CNY|HKD|SGD|INR|SEK|NOK|DKK|PLN|CZK|HUF|ZAR|BRL|MXN|KRW"
MONEY = re.compile(rf"[$€£¥₹]|\b(?:{CURRENCIES})\b|\bkr\b|\bRs\b", re.IGNORECASE)    # a currency sign or code next to an amount makes it a price
MONEY_WINDOW = 5            # characters before and after an amount looked at for MONEY


def amounts(text: str) -> List[float]:
    """the amounts in text that stand next to a currency sign or code (MONEY), as numbers"""
    found = []
    for match in AMOUNT.finditer(text or ""):
        around = text[max(0, match.start() - MONEY_WINDOW):match.start()] + " " + text[match.end():match.end() + MONEY_WINDOW]
        if not MONEY.search(around):
            continue
        whole, decimals = re.fullmatch(r"(.*?)(?:[.,](\d{1,2}))?", match.group(0)).groups()
        found.append(float(f"{re.sub(r'[^0-9]', '', whole) or 0}.{decimals or 0}"))
    return found


class PriceFinderTool(WebsearchTool):
    """searches the web for a product (WebsearchTool's search and page reading), one llm call per page reads its offers
    (FindOfferTask), only offers whose price is on the page are kept. the ranking (the cheapest, or the best match first)
    is shown under the answer: a podium of the best three and a list of more finds (the message's "prices" data, the client's
    PriceView), the reply gets the finds as text"""
    description = prompts.PRICE_FINDER_DESCRIPTION
    thresholds = (0.55, 0.6)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user ask for the best price or the cheapest offer for a product?",
        "Does the user ask you to search the shops for a product?",
        "Does the user ask for the price of a specific product model?",
        "Does the user ask which product they should buy, like the best value drill or a monitor with certain features?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "price_finder"

    @classmethod
    def prompt(cls) -> str:
        return prompts.PRICE_FINDER_PROMPT

    # ---------------------------------------------------------------- one page: its product data (WebsearchTool hooks)

    def _page_extras(self, soup, url) -> Dict[str, Any]:
        product = self._product(soup, url)
        return {"product": product} if product else {}

    def _readable(self, page: Dict[str, Any]) -> bool:
        """a product page with a price in its data is worth reading also with little text"""
        return super()._readable(page) or bool(page.get("product", {}).get("price"))

    def _product(self, soup, url) -> Dict[str, str]:
        """{"name", "price", "currency", "image"} a shop page gives search engines: json-ld Product with its offers,
        else the og/product meta tags and itemprop price. only the keys it has"""
        product = {}
        for node in self._json_ld_nodes(soup):
            types = node.get("@type") if isinstance(node.get("@type"), list) else [node.get("@type")]
            if not {"Product", "ProductGroup"} & {str(t) for t in types}:
                continue
            offers = node.get("offers") if isinstance(node.get("offers"), list) else [node.get("offers")]
            offer = next((o for o in offers if isinstance(o, dict) and (o.get("price") or o.get("lowPrice"))), {})
            product = {"name": node.get("name"), "price": offer.get("price") or offer.get("lowPrice"),
                       "currency": offer.get("priceCurrency"), "image": self._first_url(node.get("image"))}
            break

        def meta(*names) -> Optional[str]:
            for name in names:
                tag = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name}) or soup.find(attrs={"itemprop": name})
                if tag and (tag.get("content") or tag.get_text(strip=True)):
                    return tag.get("content") or tag.get_text(strip=True)
            return None

        product.setdefault("name", None)
        product["name"] = product["name"] or meta("og:title")
        product["price"] = product.get("price") or meta("product:price:amount", "og:price:amount", "price")
        product["currency"] = product.get("currency") or meta("product:price:currency", "og:price:currency", "priceCurrency")
        image = product.get("image") or meta("og:image", "og:image:url", "twitter:image")
        image = urljoin(url, image) if image else None
        product["image"] = image if image and is_public_http_url(image) else None
        return {key: " ".join(str(value).split()) for key, value in product.items() if value}

    @staticmethod
    def _first_url(image) -> Optional[str]:
        """json-ld image: a url, a list of them or an ImageObject"""
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl")
        return image if isinstance(image, str) else None

    @staticmethod
    def _information(result: Dict[str, Any], page: Optional[Dict[str, Any]]) -> Tuple[str, str, Optional[str]]:
        """(what FindOfferTask reads, the page's url, its product image) of one search result: the page's product data and
        text, the engine's snippet when the page was not readable. "" when there is nothing"""
        if not page:
            text = f"{result['title']}\n{result['snippet']}" if result.get("snippet") else ""
            return text, result["url"], None
        product = page.get("product") or {}
        data = [product["name"]] if product.get("name") else []
        if product.get("price"):
            data.append(f"price {product['price']} {product.get('currency') or ''}".strip())
        head = f"PRODUCT DATA OF THE PAGE: {'; '.join(data)}\n\n" if data else ""
        return f"{head}{result['title']}\n{page['text']}", page["url"], product.get("image")

    # ---------------------------------------------------------------- the finds and their ranking

    @staticmethod
    def _grounded(price: float, information: str) -> bool:
        """whether price stands on the page (or in its product data) as an amount next to a currency"""
        return any(abs(amount - price) < PRICE_TOLERANCE for amount in amounts(information))

    def _findings(self, query: str, search_query: str) -> List[Dict[str, Any]]:
        """the offers on the pages a search for search_query finds whose price is on their page, unranked"""
        results = self._web_search(search_query, SEARCH_RESULTS)
        if not results:
            return []
        with ThreadPoolExecutor(max_workers=PAGE_WORKERS, thread_name_prefix="price") as pool:
            pages = list(pool.map(self._extract_page, [result["url"] for result in results]))

        reads, seen = [], set()
        for result, page in zip(results, pages):
            information, url, image = self._information(result, page)
            if not information or url in seen:
                continue
            seen.add(url)
            task = FindOfferTask(question=query, information=information, infrastructure=self.infrastructure)
            self.add_sub_task(task)
            reads.append((url, information, image, task))
        self.wait_for([read[3] for read in reads])

        findings = []
        for url, information, image, task in reads:
            for offer in task.offers():
                if not self._grounded(offer["price"], information):
                    logger.debug(f"price finder dropped {offer['title']} at {offer['price']}, the price is not on {url}")
                    continue
                findings.append({**offer, "shop": offer["shop"] or self._get_org_name(url), "url": url, "image": image})
        return findings

    @staticmethod
    def _ranked(findings: List[Dict[str, Any]], rank: str) -> List[Dict[str, Any]]:
        """the finds that fit (MIN_MATCH), each once, best first: "price" the cheapest, "match" the best fitting (cheaper
        on a tie). prices in other currencies than the most found one are not compared with it, they come after"""
        unique, seen = [], set()
        for finding in findings:
            keys = {(finding["url"], finding["price"]), (finding["title"].lower(), finding["price"], finding["shop"].lower())}
            if finding["match"] >= MIN_MATCH and not keys & seen:
                seen |= keys
                unique.append(finding)
        if not unique:
            return []
        main = Counter(finding["currency"] for finding in unique).most_common(1)[0][0]
        key = (lambda f: (-f["match"], f["price"])) if rank == "match" else (lambda f: (f["price"], -f["match"]))
        return sorted((f for f in unique if f["currency"] == main), key=key) + sorted((f for f in unique if f["currency"] != main), key=key)

    def execute(self) -> None:
        try:
            query = " ".join(str(self.tool_call.get("query") or "").split())[:MAX_QUERY_LENGTH]
            if not query:
                logger.error("invalid price_finder, no query")
                return
            rank = "match" if str(self.tool_call.get("rank") or "").lower() == "match" else "price"
            MessageQueue().send_status_message("looking for prices")

            findings = self._findings(query, f"{query} {SEARCH_SUFFIX}")
            short = self.shorter(query)
            if not findings and short:
                logger.info(f"price finder found nothing for {query!r}, trying {short!r}")
                findings = self._findings(query, f"{short} {SEARCH_SUFFIX}")

            ranked = self._ranked(findings, rank)[:MAX_FINDINGS]
            if not ranked:
                self.add_result({"tool": self.name(), "text": prompts.PRICE_NONE_PART.format(query=query)})
                return

            prices = {"query": query, "rank": rank, "findings": [
                {key: finding[key] for key in ("title", "price", "currency", "shop", "url", "image", "note")} for finding in ranked]}
            self.show_data("prices", prices)
            self.add_result({"tool": self.name(), "text": self._text(prices), "prices": prices})
        except Exception as e:
            logger.error(f"failed to find prices {repr(e)}")

    @staticmethod
    def _text(prices: Dict[str, Any]) -> str:
        lines = [prompts.PRICE_FINDING_LINE.format(place=place, title=f["title"], price=f"{f['price']:.2f}", currency=f["currency"],
                                                   shop=f["shop"], note=f" ({f['note']})" if f["note"] else "")
                 for place, f in enumerate(prices["findings"], 1)]
        return prompts.PRICE_FOUND_PART.format(query=prices["query"], findings="\n".join(lines))
