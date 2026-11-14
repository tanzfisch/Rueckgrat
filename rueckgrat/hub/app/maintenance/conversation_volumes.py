from datetime import timedelta
from typing import Dict, Any
from app.tasks.task_queue import Task
from app.utils import clock
from app.utils.conversation_volume import ConversationVolume, STALE_DAYS
from .sweeper import MaintenanceTask

from app.common import get_logger
logger = get_logger()


class ConversationVolumeMaintenanceTask(MaintenanceTask):
    """removes the files of conversations (ConversationVolume) without a message for STALE_DAYS, or gone.
    no docker access: nothing pending"""
    name = "files"

    def __init__(self, db):
        self.db = db

    def _volumes(self, user_id=None) -> list[ConversationVolume]:
        try:
            return ConversationVolume.all(user_id)
        except Exception as e:
            logger.debug(f"conversation files not listed {repr(e)}")
            return []

    def stale(self, volume: ConversationVolume) -> bool:
        """no message for STALE_DAYS, or the conversation is gone. a failed read ("") is not stale"""
        last = self.db.conversation_last_activity(volume.conversation_id)
        if last is None:
            return True
        return bool(last) and clock.from_db(last[:19]) < clock.now() - timedelta(days=STALE_DAYS)

    def pending(self, user_id, limit):
        stale = [{"user_id": v.user_id, "conversation_id": v.conversation_id} for v in self._volumes(user_id) if self.stale(v)]
        return stale if limit is None else stale[:limit]

    def get_task(self, item):
        return RemoveConversationVolumeTask(item)

    def status(self):
        volumes = self._volumes()
        return {"volumes": len(volumes), "stale": sum(self.stale(v) for v in volumes)}


class RemoveConversationVolumeTask(Task):
    def __init__(self, item: dict):
        super().__init__()
        self.item = item

    def execute(self) -> None:
        ConversationVolume(self.item["user_id"], self.item["conversation_id"]).remove()

    def get_result(self) -> Dict[str, Any]:
        return {"summary": f"files of conversation {self.item['conversation_id']} removed"}
