import threading
from datetime import datetime, timedelta

from app.agent_jobs.agent_job import AgentJob
from app.agent_jobs.job_monitor import JobMonitor
from app.utils import clock
from app.utils.clock import to_db
from app.common import get_logger

logger = get_logger()


class OutreachStore:
    """#167 the held surprise / reach_out pairs, one per contact, only in memory.

    a hub restart forgets them; the next companion pass makes a new pair. thread-safe: every method takes the lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pairs = {}    # contact_id -> dict (a copy is returned, the store keeps its own)

    def put(self, pair: dict) -> bool:
        """stores the pair, replacing one already held for that contact. True if a previous pair was replaced"""
        contact_id = pair["contact_id"]
        held = {
            "user_id": pair["user_id"],
            "contact_id": contact_id,
            "conversation_id": pair["conversation_id"],
            "name": pair["name"],
            "surprise": pair["surprise"],
            "reach_out": pair["reach_out"],
            "attachments": pair.get("attachments"),
            "held_data": pair.get("held_data"),
            "source_id": pair.get("source_id"),
            "job_id": pair.get("job_id"),
            "created_at": pair["created_at"],
            "deliver_at": pair["deliver_at"],
        }
        with self._lock:
            replaced = contact_id in self._pairs
            self._pairs[contact_id] = held
            return replaced

    def get(self, contact_id: int) -> dict | None:
        """a copy of the held pair, or None"""
        with self._lock:
            pair = self._pairs.get(contact_id)
            return dict(pair) if pair else None

    def take(self, contact_id: int) -> dict | None:
        """removes the held pair and returns a copy, None if there was none"""
        with self._lock:
            pair = self._pairs.pop(contact_id, None)
            return dict(pair) if pair else None

    def drop(self, contact_id: int) -> bool:
        """drops the held pair of this contact, False if there was none"""
        with self._lock:
            return self._pairs.pop(contact_id, None) is not None

    def due(self, now: datetime) -> list[dict]:
        """copies of pairs whose window has passed, oldest first. they stay held until take or drop"""
        with self._lock:
            due = [dict(pair) for pair in self._pairs.values() if pair["deliver_at"] <= now]
        due.sort(key=lambda pair: (pair["deliver_at"], pair["contact_id"]))
        return due

    def next_due(self) -> datetime | None:
        """the earliest deliver_at still held, or None"""
        with self._lock:
            if not self._pairs:
                return None
            return min(pair["deliver_at"] for pair in self._pairs.values())

    def drop_inactive(self, is_companion) -> int:
        """drops pairs of contacts that are no longer companions. is_companion(contact_id) -> bool"""
        with self._lock:
            gone = [contact_id for contact_id in self._pairs if not is_companion(contact_id)]
            for contact_id in gone:
                del self._pairs[contact_id]
            return len(gone)


class Outreach:
    """#167 a companion's prepared reach-out: two versions of one message, held in memory instead of sent.

    if the user opens the contact (or already has it open) before deliver_at, the surprise version is posted at once;
    if the window passes first, the reach_out version is posted as a normal companion message; if the user starts
    typing or sends a message first, both are dropped. a later pass of the same contact replaces a still-held pair.
    one pending pair per contact, only in memory (OutreachStore): a hub restart forgets it, the next pass makes a
    new one. open contacts are also remembered per websocket session and are sent again after a reconnect"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._lock = threading.Lock()
                instance._db = None
                instance._tool_registry = None
                instance._store = OutreachStore()
                instance._open = {}     # session -> (user_id, contact_id, conversation_id)
                cls._instance = instance
            return cls._instance

    def configure(self, db, tool_registry=None):
        self._db = db
        self._tool_registry = tool_registry

    def store(self) -> OutreachStore:
        return self._store

    def hold(self, user_id: int, contact_id: int, conversation_id: int, name: str, surprise: str, reach_out: str,
             window: timedelta, now: datetime | None = None, source_id: int | None = None, job_id: str | None = None,
             attachments=None, held_data=None) -> tuple[int | None, str]:
        """stores the pair, or posts the surprise version at once when the contact is already open.
        replaces a still-held pair of this contact. returns (message_id or None, reason)"""
        now = now or clock.now()
        surprise, reach_out = surprise.strip(), reach_out.strip()
        if not surprise or not reach_out:
            return None, "empty text"
        if self._db is None:
            return None, "outreach not configured"
        if self._store.get(contact_id):
            logger.info(f"companion {contact_id}: replacing a held reach-out")
        self._store.put({
            "user_id": user_id, "contact_id": contact_id, "conversation_id": conversation_id, "name": name,
            "surprise": surprise, "reach_out": reach_out, "attachments": attachments, "held_data": held_data,
            "source_id": source_id, "job_id": job_id, "created_at": now, "deliver_at": now + window,
        })
        if self.is_open(user_id, contact_id):
            message_id = self.deliver_surprise(user_id, contact_id, conversation_id, now)
            return message_id, "sent" if message_id else "held, contact open but not posted"
        logger.info(f"companion {contact_id}: held a reach-out until {to_db(now + window)}")
        return None, "held"

    def on_opened(self, user_id: int, contact_id: int, conversation_id: int, session: int,
                  now: datetime | None = None) -> int | None:
        """this websocket has the contact open: remember it and post the surprise version if a pair is still held
        and the window has not passed (a due reach_out is posted as that version instead)"""
        now = now or clock.now()
        with self._lock:
            self._open[session] = (user_id, contact_id, conversation_id)
        pending = self._store.get(contact_id)
        if not pending or pending["user_id"] != user_id:
            return None
        if pending["deliver_at"] <= now:
            return self.deliver_reach_out(contact_id, now)
        return self.deliver_surprise(user_id, contact_id, conversation_id, now)

    def on_closed(self, session: int, contact_id: int | None = None):
        """this websocket left the contact, or the socket closed"""
        with self._lock:
            current = self._open.get(session)
            if current is None:
                return
            if contact_id is None or current[1] == contact_id:
                self._open.pop(session, None)

    def disconnect(self, session: int):
        self.on_closed(session)

    def on_typing(self, user_id: int, contact_id: int) -> bool:
        """the user started typing in this contact: drop a still-held pair. True if one was dropped"""
        return self._drop(user_id, contact_id, "the user started typing")

    def on_user_message(self, user_id: int, contact_id: int) -> bool:
        """the user sent a message to this contact: drop a still-held pair. True if one was dropped"""
        return self._drop(user_id, contact_id, "the user wrote first")

    def drop_contact(self, contact_id: int) -> bool:
        """drops a still-held pair, e.g. the companion was switched off. True if one was dropped"""
        if self._store.drop(contact_id):
            logger.info(f"companion {contact_id}: dropped a held reach-out (companion off)")
            return True
        return False

    def drop_inactive(self) -> int:
        """drops held pairs of contacts that are no longer companions"""
        if self._db is None:
            return 0
        dropped = self._store.drop_inactive(self._db.is_companion)
        if dropped:
            logger.info(f"dropped {dropped} held reach-out(s) of contacts that are no companions")
        return dropped

    def deliver_due(self, now: datetime | None = None) -> list[int]:
        """posts the reach_out version of every pair whose window has passed. returns their message ids"""
        if self._db is None:
            return []
        now = now or clock.now()
        posted = []
        for row in self._store.due(now):
            message_id = self.deliver_reach_out(row["contact_id"], now)
            if message_id:
                posted.append(message_id)
        return posted

    def next_due(self) -> datetime | None:
        """when the next held reach_out should be posted, or None"""
        return self._store.next_due()

    def deliver_surprise(self, user_id: int, contact_id: int, conversation_id: int,
                         now: datetime | None = None) -> int | None:
        """posts the surprise version into the conversation the user just opened (same contact)"""
        return self._deliver(contact_id, "surprise", now, conversation_id=conversation_id, user_id=user_id)

    def deliver_reach_out(self, contact_id: int, now: datetime | None = None) -> int | None:
        """posts the reach_out version into the conversation it was prepared for"""
        return self._deliver(contact_id, "reach_out", now)

    def is_open(self, user_id: int, contact_id: int) -> bool:
        """the contact is open on at least one of the user's websockets"""
        with self._lock:
            return any(uid == user_id and cid == contact_id for uid, cid, _ in self._open.values())

    def pending(self, contact_id: int) -> dict | None:
        return self._store.get(contact_id)

    def _drop(self, user_id: int, contact_id: int, reason: str) -> bool:
        pending = self._store.get(contact_id)
        if not pending or pending["user_id"] != user_id:
            return False
        if self._store.drop(contact_id):
            logger.info(f"companion {contact_id}: dropped a held reach-out ({reason})")
            return True
        return False

    def _deliver(self, contact_id: int, version: str, now: datetime | None = None, conversation_id: int | None = None,
                 user_id: int | None = None) -> int | None:
        if self._db is None:
            return None
        now = now or clock.now()
        pending = self._store.get(contact_id)
        if not pending:
            return None
        if user_id is not None and pending["user_id"] != user_id:
            return None
        if not self._db.is_companion(contact_id):
            self._store.drop(contact_id)
            logger.info(f"companion {contact_id}: dropped a held reach-out (no companion)")
            return None
        taken = self._store.take(contact_id)
        if not taken:
            return None
        text = (taken[version] or "").strip()
        if not text:
            logger.warning(f"companion {contact_id}: held {version} was empty, dropped")
            return None
        conversation_id = conversation_id or taken["conversation_id"]
        user_id = taken["user_id"]
        message_id, pushed = AgentJob.post_message(self._db, user_id, conversation_id, text, taken["name"])
        if taken.get("attachments") and self._tool_registry:
            self._tool_registry.attach_held(self._db, user_id, conversation_id, message_id, taken["attachments"], push=pushed)
        if taken.get("held_data") and self._tool_registry:
            self._tool_registry.show_held(self._db, user_id, conversation_id, message_id, taken["held_data"], push=pushed)
        if taken.get("source_id"):
            self._db.set_companion_row_message(taken["source_id"], message_id)
        if taken.get("job_id"):
            JobMonitor().report(user_id, taken["job_id"], message_id)
        logger.info(f"companion {contact_id}: posted {version} #{message_id} at {to_db(now)}, "
                    f"{'pushed' if pushed else 'stored (user not connected)'}")
        return message_id
