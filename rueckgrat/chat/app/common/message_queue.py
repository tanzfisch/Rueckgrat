from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional
import threading

from .logger import get_logger
logger = get_logger()

# the user the running code works for. the hub's JobQueue sets it while a job runs, so tools and
# jobs can call MessageQueue().send_status_message("...") without passing the user along.
# code that runs outside a job (node callbacks, the websocket loop) passes user_id= itself
current_user_id: ContextVar[Optional[int]] = ContextVar("current_user_id", default=None)

_UNSET = object()

@contextmanager
def user_scope(user_id: Optional[int]):
    """sets current_user_id for the with block (only on this thread / task)"""
    token = current_user_id.set(user_id)
    try:
        yield
    finally:
        current_user_id.reset(token)

class MessageQueue:
    """outgoing websocket messages, one queue per user.
    target user: user_id= argument, else current_user_id, else None. None is the shared queue of
    a single-client process (the node, it only talks to the hub). the hub sets require_user, then
    a message without a user is dropped with a warning instead of reaching whoever pops next"""
    _instance = None
    _lock = threading.Lock()
    require_user = False

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.queues = {}   # user_id (or None) -> deque
                cls._instance.lock = threading.Lock()
        return cls._instance

    def _push(self, data: dict, user_id=_UNSET):
        if user_id is _UNSET:
            user_id = current_user_id.get()
        if user_id is None and self.require_user:
            logger.warning(f"message without a user dropped: {str(data)[:120]}")
            return
        with self.lock:
            self.queues.setdefault(user_id, deque()).append(data)

    def set_status(self, status: str, user_id=_UNSET):
        self._push({"status": {"state": status}}, user_id)

    def send_status_message(self, message: str, user_id=_UNSET):
        self._push({"status": {"message": message}}, user_id)

    def send_data(self, data: dict, user_id=_UNSET):
        self._push(data, user_id)

    def pop_message(self, user_id: Optional[int] = None):
        """next message for this user (None = the shared queue)"""
        with self.lock:
            queue = self.queues.get(user_id)
            return queue.popleft() if queue else None
