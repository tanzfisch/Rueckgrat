import threading
from datetime import datetime, time, timedelta

from .companion_job import CompanionJob, short
from . import clock
from .clock import to_db, from_db, user_timezone, next_daily, last_occurrence, at_local

from app.common import get_logger
logger = get_logger()

MAX_SLEEP = 60                  # wall clock seconds, also picks up new companions and rows added by other paths
MIN_SLEEP = 1
PLANNING_TIME = time(0, 5)      # the only always-on row: the night planning, local time. it schedules everything else

class CompanionScheduler:
    """one thread sleeping until the next due row of the companion calendars, then running the passes one by one
    on this thread (job_queue.run): no JobQueue worker is held, chats are never starved by companions.

    catch-up after downtime: a due row fires once if its (latest) occurrence is at or after the cutoff
    max(the last local midnight, the companion's last run), older ones are marked missed without a pass.
    a daily row always re-arms to its next future occurrence, missed days are never replayed"""

    def __init__(self, db, infrastructure, tool_registry, job_queue, turns=None, is_connected=None):
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self.job_queue = job_queue
        self.turns = turns
        self.is_connected = is_connected
        self._stop = threading.Event()
        self._wake = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="companion").start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def wake(self):
        """look at the calendars now, e.g. a contact became a companion"""
        self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.error(f"companion tick failed {repr(e)}")
            self._wake.wait(self.sleep_seconds())
            self._wake.clear()

    def sleep_seconds(self, now: datetime | None = None) -> float:
        """wall clock seconds until the next due row (the companion clock may run faster)"""
        due = self.db.next_companion_due()
        if not due:
            return MAX_SLEEP
        now = now or clock.now()
        return min(MAX_SLEEP, max(MIN_SLEEP, (from_db(due) - now).total_seconds()))

    def cutoff(self, contact_id: int, tz, now: datetime) -> datetime:
        midnight = at_local(now.astimezone(tz).date(), time(0), tz)
        last_run = self.db.last_companion_run(contact_id)
        return max(midnight, from_db(last_run)) if last_run else midnight

    def seed(self, contact_id: int, tz, now: datetime):
        """a new companion: the daily night planning and a first planning right now for the rest of today"""
        local = now.astimezone(tz)
        planning = at_local(local.date(), PLANNING_TIME, tz)
        if planning <= now:
            planning = at_local(local.date() + timedelta(days=1), PLANNING_TIME, tz)
        self.db.add_companion_row(contact_id, to_db(planning), "planning", recurrence="daily")
        self.db.add_companion_row(contact_id, to_db(now), "planning", "the first day, plan the rest of today")
        logger.info(f"companion {contact_id} seeded")

    def tick(self, now: datetime | None = None) -> list[dict]:
        """drops calendars of non-companions, seeds new companions and handles every due row, oldest occurrence first.
        returns the outcomes"""
        now = now or clock.now()
        if self.db.drop_inactive_companion_rows():
            logger.info("dropped the calendar rows of contacts that are no companions")
        for contact in self.db.unseeded_companions():
            self.seed(contact["id"], user_timezone(self.db, contact["user_id"]), now)

        due, cutoffs = [], {}
        for row in self.db.due_companion_rows(to_db(now)):
            tz = user_timezone(self.db, row["user_id"])
            occurrence = from_db(row["due_at"])
            if row["recurrence"] == "daily":
                occurrence = last_occurrence(occurrence, tz, now)
            if row["contact_id"] not in cutoffs:   # before any pass of this tick, they would move the last run
                cutoffs[row["contact_id"]] = self.cutoff(row["contact_id"], tz, now)
            due.append((occurrence, row["id"], row, tz))
        due.sort(key=lambda item: item[:2])
        return [self._fire(row, tz, occurrence, cutoffs[row["contact_id"]], now) for occurrence, _, row, tz in due]

    def _fire(self, row: dict, tz, occurrence: datetime, cutoff: datetime, now: datetime) -> dict:
        if not self.db.is_companion(row["contact_id"]):
            return {"row": row["id"], "skipped": "no companion"}   # switched off during this tick, the next drops the row
        next_due = to_db(next_daily(from_db(row["due_at"]), tz, now)) if row["recurrence"] == "daily" else None

        record = {"row": row["id"], "kind": row["kind"], "note": short(row["note"]), "occurrence": to_db(occurrence)}
        if occurrence < cutoff:
            logger.info(f"companion row {row['id']} {row['kind']} missed (before {to_db(cutoff)}), no pass")
            self.db.finish_companion_row(row["id"], "missed", None, next_due=next_due)
            self.db.add_companion_log(row["contact_id"], to_db(now), {**record, "missed": f"before the cutoff {to_db(cutoff)}"})
            return {"row": row["id"], "skipped": "missed"}

        job = CompanionJob(row, self.db, self.infrastructure, self.tool_registry, tz, now, self.turns, self.is_connected)
        self.job_queue.run(job)
        outcome = job.outcome or {}   # a failed pass still closes / re-arms the row, it never fires in a loop
        self.db.finish_companion_row(row["id"], "done", to_db(now), outcome.get("result", ""), outcome.get("message_id"), next_due)
        if job.outcome is None:
            job.log.setdefault("error", "the pass failed")
        self.db.add_companion_log(row["contact_id"], to_db(now), {**record, **job.log})
        return {"row": row["id"], **outcome}
