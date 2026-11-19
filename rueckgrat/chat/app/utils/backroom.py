import threading
import time
from typing import Callable

from .hub import Hub
from app.common import get_logger
logger = get_logger()

ACTIVE = "running"


def duration_text(seconds) -> str:
    """4:05, 1:02:03, "?" without a value"""
    if seconds is None:
        return "?"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class Backroom:
    """#215 the app's view of the hub's agent jobs and task / companion passes (all contacts): the hub's snapshot ("jobs",
    on connect and get_jobs) and its job_update messages. pages listen for changes (add_listener). attach() once at start"""

    _jobs: dict[str, dict] = {}         # job_id -> the last job_update
    _received: dict[str, float] = {}    # job_id -> monotonic time it came, a running job's elapsed goes on from there
    _listeners: list[Callable[[str | None], None]] = []
    _lock = threading.Lock()

    @classmethod
    def attach(cls):
        Hub.register_incomming_message(cls.on_message)
        Hub.register_connection_state(cls.on_connection_state)

    @classmethod
    def detach(cls):
        Hub.unregister_incomming_message(cls.on_message)

    @classmethod
    def on_message(cls, message: dict):
        if "jobs" in message:
            items = (message["jobs"] or {}).get("items") or []
            now = time.monotonic()
            with cls._lock:
                cls._jobs = {item["job_id"]: item for item in items if item.get("job_id")}
                cls._received = {job_id: now for job_id in cls._jobs}
            cls._notify(None)
        if "job_update" in message:
            job = message["job_update"] or {}
            if not job.get("job_id"):
                return
            with cls._lock:
                cls._jobs[job["job_id"]] = job
                cls._received[job["job_id"]] = time.monotonic()
            cls._notify(job["job_id"])

    @classmethod
    def on_connection_state(cls, state: str):
        """back after a lost connection: the snapshot again (the hub sends it on connect too, this covers a resumed socket)"""
        if state == "reconnected":
            Hub.get_jobs()

    @classmethod
    def add_listener(cls, listener: Callable[[str | None], None]):
        """listener(job_id): that job changed, None: all of them (a snapshot)"""
        with cls._lock:
            if listener not in cls._listeners:
                cls._listeners.append(listener)

    @classmethod
    def remove_listener(cls, listener):
        with cls._lock:
            if listener in cls._listeners:
                cls._listeners.remove(listener)

    @classmethod
    def _notify(cls, job_id):
        with cls._lock:
            listeners = list(cls._listeners)
        for listener in listeners:
            try:
                listener(job_id)
            except Exception as e:
                logger.warning(f"backroom listener failed {repr(e)}")

    @classmethod
    def jobs(cls) -> list[dict]:
        """copies: the running ones first, newest first, then the finished ones, newest first"""
        with cls._lock:
            items = [dict(job) for job in cls._jobs.values()]
        items.sort(key=lambda job: job.get("started_at") or "", reverse=True)
        items.sort(key=lambda job: job.get("state") != ACTIVE)
        return items

    @classmethod
    def job(cls, job_id: str) -> dict | None:
        with cls._lock:
            job = cls._jobs.get(job_id)
            return dict(job) if job else None

    @classmethod
    def running_count(cls) -> int:
        with cls._lock:
            return sum(job.get("state") == ACTIVE for job in cls._jobs.values())

    @classmethod
    def for_report(cls, message_id) -> dict | None:
        """the job or pass whose report is that message, None if there is none"""
        if message_id is None:
            return None
        with cls._lock:
            job = next((job for job in cls._jobs.values() if job.get("report_message_id") == message_id), None)
            return dict(job) if job else None

    @classmethod
    def latest_for_source(cls, source_id) -> dict | None:
        """the newest pass of a scheduled task (its id is the pass's source_id), None if it has none in the Backroom"""
        with cls._lock:
            passes = [job for job in cls._jobs.values() if job.get("source_id") == source_id and job.get("kind") == "task"]
        return dict(max(passes, key=lambda job: job.get("started_at") or "")) if passes else None

    @classmethod
    def elapsed(cls, job_id: str):
        """seconds since the start: a running job's goes on locally since its last update, None if unknown"""
        with cls._lock:
            job = cls._jobs.get(job_id)
            if job is None or job.get("elapsed") is None:
                return None
            if job.get("state") != ACTIVE:
                return job["elapsed"]
            return job["elapsed"] + (time.monotonic() - cls._received.get(job_id, time.monotonic()))
