import threading
from datetime import datetime, time, timedelta

from .companion_job import CompanionJob, short
from .outreach import Outreach
from .task_job import TaskJob
from app.utils import clock
from app.utils.clock import to_db, from_db, user_timezone, next_occurrence, last_occurrence, at_local
from app.agent_jobs.protocol import Protocol, ProtocolStore
from app.agent_jobs.job_monitor import JobMonitor, RunningJob

from app.common import get_logger, MessageQueue
logger = get_logger()

MAX_SLEEP = 60                  # wall clock seconds, also picks up new companions and rows added by other paths
MIN_SLEEP = 1
NAME_CHARS = 40                 # #215 a pass's name in the Backroom
PLANNING_TIME = time(0, 5)      # the only always-on row: the night planning, local time. it schedules everything else
RESTART_GRACE = timedelta(minutes=5)    # a repeating user's task due this shortly before the hub started still fires

class CompanionScheduler:
    """one thread sleeping until the next due row of the companion calendars, then running the passes (CompanionJob,
    an agent job) one by one on this thread: no TaskQueue worker is held, chats are never starved by companions.

    catch-up after downtime: a due row fires once if its (latest) occurrence is at or after the cutoff
    max(the last local midnight, the companion's last run), older ones are marked missed without a pass.
    a daily row always re-arms to its next future occurrence, missed days are never replayed.

    #170 the user's tasks (rows of kind db.TASK_KIND, app.companion.user_tasks) are no part of the companion's day: they
    fire as a TaskJob, whatever the chattiness or quiet hours. a one-off task that was due while the hub was down runs late
    (its message says so), a repeating one skips the runs it missed then (due before started - RESTART_GRACE) and re-arms"""

    def __init__(self, db, infrastructure, tool_registry, started: datetime | None = None):
        """started: when the hub started (now), what a repeating task's run is missed before"""
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self._started = started or clock.now()
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
        """wall clock seconds until the next due calendar row or held reach-out (the companion clock may run faster)"""
        now = now or clock.now()
        due = []
        calendar = self.db.next_companion_due()
        if calendar:
            due.append(from_db(calendar))
        outreach = Outreach().next_due()
        if outreach:
            due.append(outreach)
        if not due:
            return MAX_SLEEP
        return min(MAX_SLEEP, max(MIN_SLEEP, (min(due) - now).total_seconds()))

    def missed(self, row: dict, occurrence: datetime, cutoff: datetime) -> str | None:
        """why a due row gets no pass, None: it fires. the companion's rows before the cutoff; a user's task only when it
        repeats and its run was due while the hub was down"""
        if row["kind"] != self.db.TASK_KIND:
            return f"before the cutoff {to_db(cutoff)}" if occurrence < cutoff else None
        if row["recurrence"] and occurrence < self._started - RESTART_GRACE:
            return f"the hub was down, started {to_db(self._started)}"
        return None

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
        Outreach().drop_inactive()
        Outreach().deliver_due(now)
        for contact in self.db.unseeded_companions():
            self.seed(contact["id"], user_timezone(self.db, contact["user_id"]), now)

        due, cutoffs = [], {}
        for row in self.db.due_companion_rows(to_db(now)):
            tz = user_timezone(self.db, row["user_id"])
            occurrence = from_db(row["due_at"])
            if row["recurrence"]:
                occurrence = last_occurrence(occurrence, tz, now, row["recurrence"])
            if row["contact_id"] not in cutoffs:   # before any pass of this tick, they would move the last run
                cutoffs[row["contact_id"]] = self.cutoff(row["contact_id"], tz, now)
            due.append((occurrence, row["id"], row, tz))
        due.sort(key=lambda item: item[:2])
        return [self._fire(row, tz, occurrence, cutoffs[row["contact_id"]], now) for occurrence, _, row, tz in due]

    def _fire(self, row: dict, tz, occurrence: datetime, cutoff: datetime, now: datetime) -> dict:
        if not self.db.is_companion(row["contact_id"]):
            return {"row": row["id"], "skipped": "no companion"}   # switched off during this tick, the next drops the row
        next_due = to_db(next_occurrence(from_db(row["due_at"]), row["recurrence"], tz, now)) if row["recurrence"] else None

        record = {"row": row["id"], "kind": row["kind"], "note": short(row["note"]), "occurrence": to_db(occurrence)}
        missed = self.missed(row, occurrence, cutoff)
        if missed:
            logger.info(f"companion row {row['id']} {row['kind']} missed ({missed}), no pass")
            self.db.finish_companion_row(row["id"], "missed", None, next_due=next_due)
            self.db.add_companion_log(row["contact_id"], to_db(now), {**record, "missed": missed})
            return {"row": row["id"], "skipped": "missed"}

        if row["kind"] == self.db.TASK_KIND:
            job = TaskJob(row, self.db, self.infrastructure, self.tool_registry, tz, now, occurrence)
        else:
            job = CompanionJob(row, self.db, self.infrastructure, self.tool_registry, tz, now)
        self._watch(job, row, occurrence)
        try:
            with MessageQueue.user_scope(row["user_id"]):    # status messages of its tool lookups go to the contact's owner only
                job.run()
        except Exception as e:
            logger.error(f"companion pass {row['kind']} contact {row['contact_id']} failed {repr(e)}")
        outcome = job.outcome or {}   # a failed pass still closes / re-arms the row, it never fires in a loop
        self.db.finish_companion_row(row["id"], "done", to_db(now), outcome.get("result", ""), outcome.get("message_id"), next_due)
        if job.outcome is None:
            job.log.setdefault("error", "the pass failed")
        self.db.add_companion_log(row["contact_id"], to_db(now), {**record, **job.log})
        self._unwatch(job, row, outcome)
        return {"row": row["id"], **outcome}

    def _watch(self, job, row: dict, occurrence: datetime):
        """#215 the pass gets a protocol (stored as it happens) and shows in the Backroom (JobMonitor) while it runs"""
        kind = "task" if row["kind"] == self.db.TASK_KIND else "companion"
        name = short(row["note"], NAME_CHARS) if kind == "task" else short(f"{row['kind'].replace('_', ' ')}: {row['note'] or ''}".rstrip(": "), NAME_CHARS)
        job.protocol = Protocol(ProtocolStore.create(self.db, job.job_id, kind, row["user_id"], name, contact_id=row["contact_id"],
                                                     source_id=row["id"], time_limit=job.time_limit))
        JobMonitor().start(RunningJob(job.job_id, kind, name, row["user_id"], job.protocol, job.time_limit,
                                      contact_id=row["contact_id"], source_id=row["id"]))
        job.trace("pass_started", kind=row["kind"], note=row["note"] or None, occurrence=to_db(occurrence), recurrence=row["recurrence"] or None)

    def _unwatch(self, job, row: dict, outcome: dict):
        """the pass's last line (what it decided, companion_log), its end and the message it sent"""
        ok = job.outcome is not None
        job.trace("pass_finished", ok=ok, result=outcome.get("result") or None, message_id=outcome.get("message_id"),
                  **{key: value for key, value in job.log.items() if key not in ("ok", "step", "task", "result", "message_id")})
        JobMonitor().finish(job.job_id, "done" if ok else "failed")
        if outcome.get("message_id"):
            JobMonitor().report(row["user_id"], job.job_id, outcome["message_id"])
