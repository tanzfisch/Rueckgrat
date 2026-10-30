import os
import threading
from datetime import datetime

from app.jobs.job_queue import Job
from app.companion import clock
from app.companion.clock import user_timezone, parse_hhmm

from app.common import get_logger
logger = get_logger()

# the nightly window, each user's local time (PUT /users/me/timezone, else DEFAULT_TIMEZONE)
QUIET_START = parse_hhmm(os.environ.get("HUB_MAINTENANCE_START") or "02:00") or parse_hhmm("02:00")
QUIET_END = parse_hhmm(os.environ.get("HUB_MAINTENANCE_END") or "05:00") or parse_hhmm("05:00")
BATCH = int(os.environ.get("HUB_MAINTENANCE_BATCH") or 50)   # items per task, user and night. the rest waits for the next night
# small runs between the nights, so new conversations don't wait a whole day. 0 minutes = off
INTERVAL_MINUTES = int(os.environ.get("HUB_MAINTENANCE_INTERVAL") or 15)
SMALL_BATCH = int(os.environ.get("HUB_MAINTENANCE_SMALL_BATCH") or 10)
CHECK_SECONDS = 60      # how often the sweeper looks at the clock, and waits while the hub is busy

class MaintenanceTask:
    """one kind of maintenance, e.g. the conversation summaries. the sweeper asks for the pending items of a user
    and runs the job of each, one after another. a new kind: subclass, then add it to the sweeper's task list (main.py)"""
    name = ""

    def pending(self, user_id: int | None, limit: int | None) -> list[dict]:
        """the work waiting for this user (None = all users), at most limit items (None = all)"""
        raise NotImplementedError

    def job(self, item: dict) -> Job:
        """the job for one item, its result() is a short outcome for the log"""
        raise NotImplementedError

    def status(self) -> dict:
        """counts for hub management"""
        return {}

def in_window(local: datetime, start=QUIET_START, end=QUIET_END) -> bool:
    if start <= end:
        return start <= local.time() < end
    return local.time() >= start or local.time() < end   # e.g. 23:00-04:00

class MaintenanceSweeper:
    """one thread: once a day, in each user's quiet window, runs the pending items of all tasks for that user.
    outside the window a small batch runs every INTERVAL_MINUTES.
    one item at a time on this thread (job_queue.run), no JobQueue worker is held. while the hub is busy
    (is_busy, e.g. a reply is being made) it waits, when the window closes it stops, the rest comes the next night"""

    def __init__(self, db, job_queue, tasks: list[MaintenanceTask], is_busy=None):
        self.db = db
        self.job_queue = job_queue
        self.tasks = tasks
        self.is_busy = is_busy or (lambda: False)
        self._done = {}   # user_id -> local date of the last finished sweep. a restart in the window sweeps again, nothing is stale then
        self._last_small = {}   # user_id -> time of the last small run
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="maintenance").start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.error(f"maintenance tick failed {repr(e)}")
            self._stop.wait(CHECK_SECONDS)

    def tick(self, now: datetime | None = None):
        """sweeps every user whose window is open and who wasn't swept on this local day yet.
        outside the window: a small batch when INTERVAL_MINUTES have passed since the last one"""
        for user in self.db.get_users():
            tz = user_timezone(self.db, user["id"])
            local = (now or clock.now()).astimezone(tz)
            if in_window(local):
                if self._done.get(user["id"]) == local.date():
                    continue
                if self.sweep(user["id"], BATCH, until=lambda: in_window(clock.now().astimezone(tz))):
                    self._done[user["id"]] = local.date()
            elif self._small_due(user["id"], local):
                self._last_small[user["id"]] = local
                self.sweep(user["id"], SMALL_BATCH)

    def _small_due(self, user_id: int, local: datetime) -> bool:
        if INTERVAL_MINUTES <= 0:
            return False
        last = self._last_small.get(user_id)
        return last is None or (local - last).total_seconds() >= INTERVAL_MINUTES * 60

    def sweep(self, user_id: int | None, limit: int | None, task_names: list[str] | None = None, until=None) -> bool:
        """runs the pending items of the tasks for a user (None = all users). until: False stops the sweep (window closed).
        True if the sweep got through"""
        for task in self.tasks:
            if task_names and task.name not in task_names:
                continue
            items = task.pending(user_id, limit)
            if items:
                logger.info(f"maintenance {task.name}: {len(items)} item(s) for user {user_id}")
            for item in items:
                if not self._wait_quiet(until):
                    logger.info(f"maintenance {task.name}: window closed, the rest waits for the next night")
                    return False
                job = task.job(item)
                self.job_queue.run(job)
                logger.info(f"maintenance {task.name}: {job.result()}")
        return True

    def _wait_quiet(self, until) -> bool:
        """waits while the hub is busy. False if the window closed or the hub stops"""
        while not self._stop.is_set():
            if until and not until():
                return False
            if not self.is_busy():
                return True
            self._stop.wait(CHECK_SECONDS)
        return False
