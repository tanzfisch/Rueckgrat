import re
from typing import Dict, Any, List
from . import prompts
from .find_answer_task import FindAnswerTask

from app.common import get_logger
logger = get_logger()

MAX_OFFERS = 3          # offers of one page, a price comparison page lists several shops
MAX_TITLE = 120
MAX_NOTE = 100
CURRENCY = re.compile(r"[A-Z]{3}")


class FindOfferTask(FindAnswerTask):
    """the price finder's offers on one page: one llm call reads the page's product data and text (FindAnswerTask with
    FIND_OFFER_PROMPT), the result is {"offers": [{"title", "price", "currency", "shop", "match", "note"}]}.
    the prices are what the llm read, PriceFinderTool keeps only those it finds in the page"""
    PROMPT = prompts.FIND_OFFER_PROMPT

    def _answer(self, reply) -> Dict[str, Any]:
        offers = reply.get("offers") if isinstance(reply, dict) else None
        return {"offers": [offer for offer in map(self._offer, offers if isinstance(offers, list) else []) if offer][:MAX_OFFERS]}

    @staticmethod
    def _offer(raw) -> Dict[str, Any] | None:
        """one offer of the reply in a certain structure, None without a title or a positive price"""
        if not isinstance(raw, dict):
            return None
        try:
            price = float(str(raw.get("price")).replace(",", ""))
            match = int(float(raw.get("match") or 0))
        except (TypeError, ValueError):
            return None
        title = " ".join(str(raw.get("title") or "").split())[:MAX_TITLE]
        if not title or price <= 0:
            return None
        currency = str(raw.get("currency") or "").strip().upper()
        return {
            "title": title,
            "price": price,
            "currency": currency if CURRENCY.fullmatch(currency) else "",
            "shop": " ".join(str(raw.get("shop") or "").split())[:MAX_TITLE],
            "match": max(1, min(10, match)),
            "note": " ".join(str(raw.get("note") or "").split())[:MAX_NOTE],
        }

    def offers(self) -> List[Dict[str, Any]]:
        return (self.get_result() or {}).get("offers") or []
