from typing import Dict, Any
from .tool import Tool
from . import prompts

from app.common import get_logger, MessageQueue
from app.utils.embeddings import embed_text
logger = get_logger()

MAX_QUERY_LENGTH = 200
MAX_RESULTS = 5
MAX_CONVERSATIONS = 3     # earlier conversations, from the summaries of the nightly maintenance (app/maintenance)
SNIPPET_CHARS = 300
# the vector search only ranks: every candidate conversation gets a yes/no check with laya (like ToolDetectionTask), the no's are dropped
CONVERSATION_THRESHOLD = 0.5   # relevant above this P(true). a guess, like the tool thresholds (tool_detection_task)

class SearchMemoryTool(Tool):
    description = prompts.SEARCH_MEMORY_DESCRIPTION
    requires = ("embedding",)
    question = []

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "search_memory"

    def execute(self) -> None:
        query = " ".join(str(self.tool_call.get("query") or "").split())[:MAX_QUERY_LENGTH]
        if not query:
            logger.error("empty query to search memory")
            return

        vector = embed_text(self.infrastructure, query, query=True)
        if vector is None:
            logger.error("memory search unavailable (no embedding model)")
            return

        MessageQueue().send_status_message("searching memories")

        # two separate indexes, one vector: the contact's memories and the summaries of its other conversations
        memories = self.db.nearest_contact_memories(self.get_user_id(), self.contact_id, vector, k=MAX_RESULTS)
        conversations = self.db.nearest_conversations(self.get_user_id(), vector, k=MAX_CONVERSATIONS, contact_id=self.contact_id,
                                                      exclude_id=self.get_conversation_id())
        
        conversations = self._relevant(query, conversations)
        logger.debug(f"search_memory: user {self.get_user_id()} contact {self.contact_id}, {len(memories)} memories {[m['id'] for m in memories]}, "
                     f"conversations {[c['id'] for c in conversations]}")
        conversation_results = [
            {"conversation_id": c["id"], "contact": c["contact"], "date": str(c["created_at"])[:10], "snippet": c["summary"][:SNIPPET_CHARS]}
            for c in conversations
        ]

        if not memories and not conversations:
            logger.debug("no relevabt memories found")
            return

        lines = []
        if memories:
            lines += ["Memories:"] + [f"{i}. ({str(m['created_at'])[:10]}) {m['text']}" for i, m in enumerate(memories, 1)]
        if conversations:
            lines += ["Earlier conversations:"] + [f"{i}. (conversation {c['conversation_id']}, {c['date']}) {c['snippet']}"
                                                   for i, c in enumerate(conversation_results, 1)]

        result = {
            "tool": self.name(), 
            "text": "\n" + "\n".join(lines)
        }
        self.add_result(result)

    def _relevant(self, query: str, conversations: list) -> list:
        """the conversations laya says are about the query, all questions in one forward pass.
        without an answer from laya (no decision node, it failed) all candidates are kept"""
        if not conversations:
            return []
        questions = {str(c["id"]): {"type": "noul", "instructions": prompts.SEARCH_MEMORY_CONVERSATION_QUESTION_PART.format(summary=c["summary"][:SNIPPET_CHARS])}
                     for c in conversations}
        answers = self.infrastructure.decide(f"The user's question: {query}", questions)
        if answers is None:
            logger.warning("search_memory: no laya decisions, earlier conversations not checked for relevance")
            return conversations
        probabilities = {key: (answers.get(key) or {}).get("noul", 1.0) for key in questions}   # a missing answer keeps it
        logger.debug(f"search_memory conversation probabilities: {probabilities}")
        return [c for c in conversations if probabilities[str(c["id"])] >= CONVERSATION_THRESHOLD]

    @classmethod
    def prompt(cls) -> str:
        return prompts.SEARCH_MEMORY_PROMPT
