from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional
import itertools
import threading

from .logger import get_logger
logger = get_logger()

_UNSET = object()

class MessageQueue:
    _instance = None
    _lock = threading.Lock()
    _current_user_id: ContextVar[Optional[int]] = ContextVar("current_user_id", default=None)    # the user the running code works for
    _current_session: ContextVar[Optional[int]] = ContextVar("current_session", default=None)   # the websocket that asked for it (connect)
    _current_conversation: ContextVar[Optional[int]] = ContextVar("current_conversation", default=None)   # status messages carry it
    _require_user = False       # True: a message without a user is dropped (the hub, many users). False: it goes to the shared queue (the node)
    _quiet: ContextVar[bool] = ContextVar("quiet", default=False)   # status messages are dropped, data still goes out

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.queues = {}   # user_id (or None: the node) -> deque, the messages of a user without an open websocket
                cls._instance.sessions = {}     # session -> (user_id, deque), one per open websocket of a user (connect)
                cls._instance.session_ids = itertools.count(1)
                cls._instance.lock = threading.Lock()
        return cls._instance

    @classmethod
    @contextmanager
    def user_scope(cls, user_id: Optional[int], session: Optional[int] = None, conversation_id: Optional[int] = None):
        """the messages of the code inside go to user_id: to the websocket session only (the one that asked) while it is
        open, else to all the user's websockets. status messages carry conversation_id"""
        tokens = [(var, var.set(value)) for var, value in ((cls._current_user_id, user_id), (cls._current_session, session),
                                                            (cls._current_conversation, conversation_id))]
        try:
            yield
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    @classmethod
    @contextmanager
    def quiet_scope(cls):
        """the code inside sends no status messages: it runs after the reply's status ended (a detached tool call),
        a late status would show up as a waiting reply"""
        token = cls._quiet.set(True)
        try:
            yield
        finally:
            cls._quiet.reset(token)

    @classmethod
    def get_current_user(cls) -> Optional[int]:
        return cls._current_user_id.get()

    @classmethod
    def get_current_session(cls) -> Optional[int]:
        return cls._current_session.get()

    @classmethod
    def get_current_conversation(cls) -> Optional[int]:
        return cls._current_conversation.get()

    def connect(self, user_id: int) -> int:
        """a new websocket of the user: its session id for user_scope and pop_message. it takes the messages that waited
        for the user while no websocket was open"""
        with self.lock:
            session = next(self.session_ids)
            self.sessions[session] = (user_id, self.queues.pop(user_id, None) or deque())
            return session

    def disconnect(self, session: int):
        """the websocket is closed: what was on its way to it is dropped, later messages of its turns go to the user's other websockets"""
        with self.lock:
            self.sessions.pop(session, None)

    @classmethod
    def set_require_user(cls, required: bool):        
        cls._require_user = required

    @classmethod
    def get_require_user(cls) -> bool:
        return cls._require_user

    def _push(self, data: dict, user_id=_UNSET, session=_UNSET):
        """to the session's websocket (default: the scope's session if the scope is user_id's) while it is open, else to
        all of the user's websockets, else to the user's queue until one connects"""
        if user_id is _UNSET:
            user_id = self.get_current_user()
        if session is _UNSET:
            session = self.get_current_session() if user_id == self.get_current_user() else None

        if user_id is None and self.get_require_user():
            logger.warning(f"message without a user dropped: {str(data)[:120]}")
            return
        
        with self.lock:
            own = self.sessions.get(session)
            if own and own[0] == user_id:
                own[1].append(data)
                return
            queues = [queue for owner, queue in self.sessions.values() if owner == user_id] or [self.queues.setdefault(user_id, deque())]
            for queue in queues:
                queue.append(data)

    def _push_status(self, status: dict, user_id, conversation_id):
        if self._quiet.get():
            return
        if conversation_id is _UNSET:
            conversation_id = self.get_current_conversation() if user_id in (_UNSET, self.get_current_user()) else None
        if conversation_id is not None:
            status["conversation_id"] = conversation_id     # the app shows it only in that conversation
        self._push({"status": status}, user_id)

    def set_status(self, status: str, user_id=_UNSET, conversation_id=_UNSET):
        self._push_status({"state": status}, user_id, conversation_id)

    def send_status_message(self, message: str, user_id=_UNSET, conversation_id=_UNSET):
        self._push_status({"message": message}, user_id, conversation_id)

    def send_job_progress(self, job_id: str, name: str, percent: int, state: str = "running",
                          step: Optional[int] = None, total: Optional[int] = None, user_id=_UNSET):
        self._push(
                {"job_progress": {
                "job_id": job_id, 
                "name": name, 
                "percent": max(0, min(100, int(percent))), 
                "state": state,
                "step": step, 
                "total": total
                }}, user_id)

    def send_data(self, data: dict, user_id=_UNSET, session=_UNSET):
        self._push(data, user_id, session)

    def pop_message(self, user_id: Optional[int] = None, session: Optional[int] = None):
        """the next message of the websocket session (connect), without a session the next one of the user's queue (the node)"""
        with self.lock:
            queue = self.sessions.get(session, (None, None))[1] if session is not None else self.queues.get(user_id)
            return queue.popleft() if queue else None
