from typing import Dict, Any
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
from app.utils.embeddings import embed_text
logger = get_logger()

MAX_QUERY_LENGTH = 200
MAX_RESULTS = 5

class SearchMemoryTool(Tool):
    category = ToolCategory.MEMORY
    description = ("what the user told you before (name, where they live, family, work, plans, preferences, etc). "
                   "Use for any personal question about the user, e.g. \"do you know where I was born?\", even without \"remember\"")
    question = ""

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "search_memory"

    def execute(self) -> None:
        query = " ".join(str(self.tool_call.get("query") or "").split())[:MAX_QUERY_LENGTH]
        if not query:
            logger.error("search_memory: empty query")
            self._add_result({"tool": self.name(), "error": "nothing to search for"})
            return

        vector = embed_text(self.infrastructure, query, query=True)
        if vector is None:
            self._add_result({"tool": self.name(), "error": "memory search unavailable (no embedding model)"})
            return

        MessageQueue().send_status_message("searching memories")
        memories = self.db.nearest_contact_memories(self.user_id, self.contact_id, vector, k=MAX_RESULTS)
        logger.debug(f"search_memory: user {self.user_id} contact {self.contact_id}, {len(memories)} memories {[m['id'] for m in memories]}")
        if not memories:
            self._add_result({"tool": self.name(), "text": "no memories found"})
            return

        # closest first, created_at is "YYYY-MM-DD HH:MM:SS" (UTC), the date is enough
        lines = [f"{i}. ({str(m['created_at'])[:10]}) {m['text']}" for i, m in enumerate(memories, 1)]
        self._add_result({"tool": self.name(), "text": "\n" + "\n".join(lines)})

    def _add_result(self, result: Dict[str, Any]) -> None:
        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
SEARCH MEMORY:

Call this tool whenever you need to recall a fact about the user or anything from past interactions with them (name, location, family, work, preferences, previous statements, etc.). Do not guess or invent details.

Parameters:
- query (string, required): what to look for (max 100 characters)

Example:
{"tool": "search_memory", "query": "where the user lives"}
"""
