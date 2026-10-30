from typing import Dict, Any
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
from app.utils.embeddings import embed_text
logger = get_logger()

MAX_QUERY_LENGTH = 200
MAX_RESULTS = 5
MAX_CONVERSATIONS = 3     # earlier conversations, from the summaries of the nightly maintenance (app/maintenance)
SNIPPET_CHARS = 300
# the vector search only ranks: every candidate conversation gets a yes/no check with laya (like ToolDetectionJob), the no's are dropped
CONVERSATION_QUESTION = "Is this earlier conversation about the user's question? Summary of the conversation: {summary}"
CONVERSATION_THRESHOLD = 0.5   # relevant above this P(true). a guess, like TOOL_THRESHOLD

class SearchMemoryTool(Tool):
    category = ToolCategory.MEMORY
    description = ("what the user told you before (name, where they live, family, work, plans, preferences, etc) and what you talked about in earlier conversations. "
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
        # two separate indexes, one vector: the contact's memories and the summaries of its other conversations
        memories = self.db.nearest_contact_memories(self.user_id, self.contact_id, vector, k=MAX_RESULTS)
        conversations = self.db.nearest_conversations(self.user_id, vector, k=MAX_CONVERSATIONS, contact_id=self.contact_id,
                                                      exclude_id=self.conversation_id)
        conversations = self._relevant(query, conversations)
        logger.debug(f"search_memory: user {self.user_id} contact {self.contact_id}, {len(memories)} memories {[m['id'] for m in memories]}, "
                     f"conversations {[c['id'] for c in conversations]}")
        self.response["conversation_results"] = [
            {"conversation_id": c["id"], "contact": c["contact"], "date": str(c["created_at"])[:10], "snippet": c["summary"][:SNIPPET_CHARS]}
            for c in conversations
        ]
        if not memories and not conversations:
            self._add_result({"tool": self.name(), "text": "no memories found"})
            return

        # closest first, created_at is "YYYY-MM-DD HH:MM:SS" (UTC), the date is enough
        lines = []
        if memories:
            lines += ["Memories:"] + [f"{i}. ({str(m['created_at'])[:10]}) {m['text']}" for i, m in enumerate(memories, 1)]
        if conversations:
            lines += ["Earlier conversations:"] + [f"{i}. (conversation {c['conversation_id']}, {c['date']}) {c['snippet']}"
                                                   for i, c in enumerate(self.response["conversation_results"], 1)]
        self._add_result({"tool": self.name(), "text": "\n" + "\n".join(lines)})

    def _relevant(self, query: str, conversations: list) -> list:
        """the conversations laya says are about the query, all questions in one forward pass.
        without an answer from laya (no decision node, it failed) all candidates are kept"""
        if not conversations:
            return []
        questions = {str(c["id"]): {"type": "noul", "instructions": CONVERSATION_QUESTION.format(summary=c["summary"][:SNIPPET_CHARS])}
                     for c in conversations}
        answers = self.infrastructure.decide(f"The user's question: {query}", questions)
        if answers is None:
            logger.warning("search_memory: no laya decisions, earlier conversations not checked for relevance")
            return conversations
        probabilities = {key: (answers.get(key) or {}).get("noul", 1.0) for key in questions}   # a missing answer keeps it
        logger.debug(f"search_memory conversation probabilities: {probabilities}")
        return [c for c in conversations if probabilities[str(c["id"])] >= CONVERSATION_THRESHOLD]

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
