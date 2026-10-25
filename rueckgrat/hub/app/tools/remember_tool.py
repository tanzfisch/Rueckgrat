from typing import Dict, Any
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
from app.utils.embeddings import embed_text
logger = get_logger()

MAX_MEMORY_LENGTH = 200
# cosine distance below which a new memory counts as one the contact already has (bge-small: rewordings ~0.01-0.02, "likes tea" vs "does not like tea" ~0.09)
DUPLICATE_DISTANCE = 0.05

class RememberTool(Tool):
    category = ToolCategory.MEMORY
    description = "save one short fact to remember in later conversations (about the user, their life, plans, preferences or your relationship)"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "remember"

    def execute(self) -> None:
        text = " ".join(str(self.tool_call.get("text") or "").split())
        if not text or len(text) > MAX_MEMORY_LENGTH:
            logger.error("invalid info to remember")
            self.response.setdefault("tool_results", []).append({"tool": self.name(), "error": "remembered nothing"})
            return

        MessageQueue().send_status_message("remembering")
        # embed first: a memory that means the same as one the contact already has is not saved again
        vector = embed_text(self.infrastructure, text)
        if vector is not None:
            closest = self.db.nearest_contact_memories(self.user_id, self.contact_id, vector, k=1)
            if closest and closest[0]["distance"] < DUPLICATE_DISTANCE:
                logger.debug(f"remember: contact {self.contact_id} already remembers this as memory {closest[0]['id']}, nothing saved")
                self.response.setdefault("tool_results", []).append({"tool": self.name(), "text": f"already remembered: {closest[0]['text']}"})
                return

        memory_id = self.db.add_contact_memory(self.user_id, self.contact_id, text)
        if memory_id is None:
            logger.error(f"remember: not saved, contact {self.contact_id} is not a contact of user {self.user_id}")
            result = {"tool": self.name(), "error": "could not save the memory"}
        else:
            logger.debug(f"remembered memory {memory_id} for user {self.user_id} contact {self.contact_id} ({len(text)} characters)")
            # the memory is saved either way, without a vector search_memory just won't find it
            if vector is None or not self.db.set_memory_embedding(self.user_id, memory_id, vector):
                logger.warning(f"remember: memory {memory_id} saved without a vector")
            result = {"tool": self.name(), "text": f"saved: {text}"}

        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
REMEMBER:
Use to store one short fact for later conversations. One fact per call, third person, max 200 characters.

Parameters:
- text (string, required): the fact to remember

Example:
{"tool": "remember", "text": "The user's sister is called Anna and lives in Hamburg"}
"""
