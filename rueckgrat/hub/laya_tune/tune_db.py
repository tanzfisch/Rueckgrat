"""An in-memory conversation for laya_tune's stack mode: no real database and no files."""
from typing import Any, Dict, List, Optional


class TuneDb:
    """the messages already in a conversation, before the row's user turn. reads only, add_message is a no-op"""

    def __init__(self, history: Optional[List[Dict[str, Any]]] = None, *, user_id: int = 1, contact_id: int = 1,
                 conversation_id: int = 1, name: str = "Kai", timezone: str = "Pacific/Auckland"):
        self.user_id = user_id
        self.contact_id = contact_id
        self.conversation_id = conversation_id
        self._name = name
        self._timezone = timezone
        self._messages: List[Dict[str, Any]] = []
        for message in history or []:
            self._append(message)

    def _append(self, message: Dict[str, Any]) -> Dict[str, Any]:
        entry = {
            "id": message.get("id") or (len(self._messages) + 1),
            "role": message["role"],
            "content": message.get("content") or "",
            "name": message.get("name") or (self._name if message["role"] == "assistant" else "user"),
            "sources": message.get("sources") or [],
            "data": message.get("data") or {},
        }
        self._messages.append(entry)
        return entry

    def get_message_count_by_conversation(self, conversation_id: int) -> int:
        return len(self._messages)

    def get_messages_by_conversation(self, conversation_id: int, max_messages: int) -> List[Dict[str, Any]]:
        return list(self._messages[-max_messages:] if max_messages else self._messages)

    def get_contact_by_id(self, contact_id: int) -> Dict[str, Any]:
        return {"id": contact_id, "identity": {"name": self._name}}

    def get_conversation(self, conversation_id: int) -> Dict[str, Any]:
        return {"id": conversation_id, "context": ""}

    def get_user_timezone(self, user_id: int) -> Optional[str]:
        return self._timezone

    def get_device_timezone(self, user_id: int) -> Optional[str]:
        return None

    def add_message(self, conversation_id: int, role: str, content: str, name: str) -> int:
        """accepted so a leftover caller cannot write a real db; the new message is kept only in memory"""
        return self._append({"role": role, "content": content, "name": name})["id"]
