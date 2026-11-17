import os
import re
from datetime import datetime, date, timedelta

from app.utils import clock
from app.utils.clock import to_db, from_db, user_timezone, at_local, parse_hhmm, every_minutes, first_occurrence, EVERY_PREFIX

from app.common import get_logger
logger = get_logger()

# per user, set by the installer (HUB_TASKS_MAX, HUB_TASKS_MIN_INTERVAL in .env, see compose.yml)
MAX_TASKS = int(os.environ.get("HUB_TASKS_MAX") or 20)                       # open tasks over all contacts
MIN_INTERVAL_MINUTES = int(os.environ.get("HUB_TASKS_MIN_INTERVAL") or 15)   # the shortest "every N minutes"
MAX_DAYS_AHEAD = 366
MAX_TEXT = 500

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NO_REPEAT = {"", "none", "no", "once", "one time", "never", "false", "null", "not"}
REPEAT_WORDS = {
    "hourly": f"{EVERY_PREFIX}60", "every hour": f"{EVERY_PREFIX}60", "each hour": f"{EVERY_PREFIX}60",
    "daily": "daily", "every day": "daily", "each day": "daily", "every morning": "daily", "every evening": "daily", "every night": "daily",
    "weekdays": "weekdays", "every weekday": "weekdays", "workdays": "weekdays", "every workday": "weekdays",
    "monday to friday": "weekdays", "mon-fri": "weekdays",
    "weekly": "weekly", "every week": "weekly", "each week": "weekly",
}
UNIT_MINUTES = {"w": 7 * 24 * 60, "d": 24 * 60, "h": 60, "m": 1}
DURATION = re.compile(r"(\d+(?:\.\d+)?|an?|half an?|one)\s*(weeks?|w|days?|d|hours?|hrs?|hr|h|minutes?|mins?|min|m)\b")
EVERY = re.compile(r"(?:every|each)\s+(\d+)?\s*(hours?|hrs?|h|minutes?|mins?|min|m)")
TIME_OF_DAY = re.compile(r"\b(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?(?=\s|$)")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[t\s]|$)")


class TaskError(ValueError):
    """a task that can not be made or changed, the message says why in words for the user"""


class TaskNotFound(LookupError):
    """no open task or contact of the user with that id"""


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return bool(value)


class UserTasks:
    """#170 the user's tasks: something the contact does at a given time, once or repeatedly. a task is a row of kind
    ChatDB.TASK_KIND in the contact's companion calendar, CompanionScheduler fires it (TaskJob). the task tool and the
    /tasks routes share this class: its checks and limits are the same for both. times are the user's local time"""

    def __init__(self, db, wake=None, max_tasks: int = MAX_TASKS, min_interval: int = MIN_INTERVAL_MINUTES):
        """wake: called after a change, the scheduler looks at the calendars again (CompanionScheduler.wake)"""
        self._db = db
        self._wake = wake
        self._max_tasks = max_tasks
        self._min_interval = min_interval

    @property
    def max_tasks(self) -> int:
        return self._max_tasks

    @property
    def min_interval(self) -> int:
        return self._min_interval

    def limits(self) -> dict:
        return {"max_tasks": self._max_tasks, "min_interval_minutes": self._min_interval}

    # ------------------------------------------------------------ the actions

    def list(self, user_id: int, contact_id: int | None = None) -> list[dict]:
        """the user's open tasks (view), of one contact or all, next first"""
        tz = user_timezone(self._db, user_id)
        return [self._view(row, tz) for row in self._db.get_tasks(user_id, contact_id)]

    def get(self, user_id: int, task_id: int) -> dict:
        rows = self._db.get_tasks(user_id, task_id=task_id)
        if not rows:
            raise TaskNotFound(f"no open task #{task_id}")
        return self._view(rows[0], user_timezone(self._db, user_id))

    def create(self, user_id: int, contact_id: int, text, when, repeat=None, alarm=False, conversation_id: int | None = None,
               now: datetime | None = None) -> dict:
        """a new task, its view with "companion_switched_on": True when the contact was no companion (tasks only run for
        companions, it is switched on). conversation_id: where it was asked for, None: the contact's latest conversation.
        TaskError for invalid values or the limit, TaskNotFound for a contact of someone else"""
        if not self._db.owns_contact(user_id, contact_id):
            raise TaskNotFound("contact not found")
        text = self._text(text)
        if self._db.count_tasks(user_id) >= self._max_tasks:
            raise TaskError(f"the limit of {self._max_tasks} open tasks is reached, cancel one first")
        recurrence = self.parse_repeat(repeat)
        tz = user_timezone(self._db, user_id)
        due = self.parse_when(when, recurrence, tz, now or clock.now())
        if conversation_id is None or not self._db.owns_conversation(user_id, conversation_id):
            conversations = self._db.get_conversations(user_id, contact_id)
            conversation_id = conversations[0]["id"] if conversations else None    # none: TaskJob opens one
        switched = not self._db.is_companion(contact_id)
        if switched:
            self._db.set_contact_companion(user_id, contact_id, True)
            logger.info(f"task: companion mode of contact {contact_id} switched on")
        task_id = self._db.add_companion_row(contact_id, to_db(due), self._db.TASK_KIND, text, recurrence, _flag(alarm), conversation_id)
        logger.info(f"task {task_id} created for contact {contact_id}: {recurrence or 'once'} from {to_db(due)}")
        self._changed()
        return {**self.get(user_id, task_id), "companion_switched_on": switched}

    def edit(self, user_id: int, task_id: int, text=None, when=None, repeat=None, alarm=None, now: datetime | None = None) -> dict:
        """changes the given values of an open task (None: stays). a new repeat without a new when keeps its time"""
        task = self.get(user_id, task_id)
        tz = user_timezone(self._db, user_id)
        text = task["task"] if text is None else self._text(text)
        recurrence = task["repeat"] if repeat is None else self.parse_repeat(repeat)
        if when is not None and str(when).strip():
            due = self.parse_when(when, recurrence, tz, now or clock.now())
        else:
            due = first_occurrence(from_db(task["next_run"]), recurrence, tz)
        alarm = task["alarm"] if alarm is None else _flag(alarm)
        if not self._db.update_task(user_id, task_id, to_db(due), recurrence, text, alarm):
            raise TaskNotFound(f"no open task #{task_id}")
        self._changed()
        return self.get(user_id, task_id)

    def cancel(self, user_id: int, task_id: int) -> dict:
        """deletes an open task, returns what it was"""
        task = self.get(user_id, task_id)
        if not self._db.delete_task(user_id, task_id):
            raise TaskNotFound(f"no open task #{task_id}")
        logger.info(f"task {task_id} cancelled")
        self._changed()
        return task

    def _changed(self):
        if self._wake:
            self._wake()

    # ------------------------------------------------------------ the values

    @staticmethod
    def _text(text) -> str:
        text = " ".join(str(text or "").split())
        if not text:
            raise TaskError("the task has no text, say what to do")
        return text[:MAX_TEXT]

    def parse_repeat(self, repeat) -> str:
        """the stored recurrence (clock.RECURRENCES or "minutes:N") of "once", "hourly", "daily", "weekdays", "weekly",
        "every N minutes" or "every N hours". TaskError for anything else or an interval below the limit"""
        key = " ".join(str(repeat if repeat is not None else "").lower().replace("_", " ").split())
        if key in NO_REPEAT:
            return ""
        recurrence = REPEAT_WORDS.get(key)
        if recurrence is None and every_minutes(key) is not None:
            recurrence = key
        match = EVERY.fullmatch(key) or re.fullmatch(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|min|m)", key)
        if recurrence is None and match:
            recurrence = f"{EVERY_PREFIX}{int(match[1] or 1) * (60 if match[2].startswith('h') else 1)}"
        if recurrence is None and key in ("every 1 day", "every 1 days"):
            recurrence = "daily"
        if recurrence is None:
            raise TaskError(f"unknown repeat '{repeat}': once, hourly, daily, weekdays, weekly, every N minutes or every N hours")
        minutes = every_minutes(recurrence)
        if minutes is not None and minutes < self._min_interval:
            raise TaskError(f"a task can repeat at most every {self._min_interval} minutes")
        return recurrence

    @staticmethod
    def repeat_text(recurrence: str) -> str:
        minutes = every_minutes(recurrence)
        if minutes is None:
            return recurrence or "once"
        if minutes == 60:
            return "hourly"
        if minutes % 60 == 0:
            return f"every {minutes // 60} hours"
        return f"every {minutes} minutes"

    def parse_when(self, when, recurrence: str, tz, now: datetime) -> datetime:
        """the first run of a task asked for when (the user's local time): "in 20 minutes", "in 1 hour 30 minutes", "now",
        "07:30", "7pm", "tomorrow 07:30", "friday 18:00", "2026-11-18 07:30". a time of day without a day is the next one.
        empty for a repeating task: now plus one interval. TaskError if it is unclear or in the past"""
        text = " ".join(str(when or "").lower().replace(",", " ").split())
        minutes = every_minutes(recurrence)
        if not text:
            if minutes is None:
                raise TaskError("when is missing: a time like 07:30, a day and time, or a delay like 'in 20 minutes'")
            return now + timedelta(minutes=minutes)
        if text in ("now", "right now", "immediately"):
            return now
        delay = self._delay(text)
        due = now + delay if delay is not None else self._time_of_day(text, tz, now)
        due = first_occurrence(due, recurrence, tz)
        if due > now + timedelta(days=MAX_DAYS_AHEAD):
            raise TaskError(f"'{when}' is more than {MAX_DAYS_AHEAD} days ahead")
        return due

    @staticmethod
    def _delay(text: str) -> timedelta | None:
        """'in 20 minutes', '1h 30m', 'in an hour and a half' -> the delay, None if text is no delay"""
        rest = re.sub(r"^in\s+", "", text)
        rest = rest.replace(" and a half", " 30m") if re.match(r"^(an?|one)\s+hours?", rest) else rest
        rest = re.sub(r"\band\b|\bfrom now\b|\blater\b", " ", rest)
        found = DURATION.findall(rest)
        if not found or DURATION.sub("", rest).strip():
            return None
        total = 0.0
        for amount, unit in found:
            count = 0.5 if amount.startswith("half") else 1 if amount in ("a", "an", "one") else float(amount)
            total += count * UNIT_MINUTES[unit[0]]
        return timedelta(minutes=total) if total > 0 else None

    @staticmethod
    def _time_of_day(text: str, tz, now: datetime) -> datetime:
        local = now.astimezone(tz)
        day, rest = None, f" {text} "
        iso = ISO_DATE.search(text)
        if iso:
            try:
                day = date(int(iso[1]), int(iso[2]), int(iso[3]))
            except ValueError:
                raise TaskError(f"'{text}' is no valid date")
            rest = rest.replace(iso[0].strip(), " ")
        for word, offset in (("today", 0), ("tonight", 0), ("tomorrow", 1)):
            if f" {word} " in rest:
                day, rest = local.date() + timedelta(days=offset), rest.replace(f" {word} ", " ")
        weekday = next((i for i, name in enumerate(WEEKDAYS) if re.search(rf"\b(?:next\s+|on\s+)?{name}\b", rest)), None)
        if weekday is not None:
            rest = re.sub(rf"\b(?:next\s+|on\s+)?{WEEKDAYS[weekday]}\b", " ", rest)
        rest = re.sub(r"\b(at|um|o'clock|h)\b", " ", rest).strip()

        match = TIME_OF_DAY.fullmatch(rest) if rest else None
        if not match:
            raise TaskError(f"'{text}' is no time I understand: say e.g. 07:30, tomorrow 07:30, 2026-11-18 07:30 or in 20 minutes")
        hour, minute, half = int(match[1]), int(match[2] or 0), (match[3] or "").replace(".", "")
        if half:
            if not 1 <= hour <= 12:
                raise TaskError(f"'{text}' is no valid time")
            hour = hour % 12 + (12 if half == "pm" else 0)
        at = parse_hhmm(f"{hour}:{minute:02d}")
        if at is None:
            raise TaskError(f"'{text}' is no valid time")

        if day is None and weekday is not None:
            day = local.date() + timedelta(days=(weekday - local.weekday()) % 7)
            if at_local(day, at, tz) <= now:
                day += timedelta(days=7)
        if day is None:     # a time of day alone: the next one
            due = at_local(local.date(), at, tz)
            return due if due > now else at_local(local.date() + timedelta(days=1), at, tz)
        due = at_local(day, at, tz)
        if due < now - timedelta(minutes=1):
            raise TaskError(f"'{text}' is in the past")
        return max(due, now)

    # ------------------------------------------------------------ how a task looks

    def _view(self, row: dict, tz) -> dict:
        due = from_db(row["due_at"]).astimezone(tz)
        return {
            "id": row["id"],
            "contact_id": row["contact_id"],
            "contact_name": row.get("contact_name") or "",
            "task": row["note"],
            "repeat": row["recurrence"],
            "repeat_text": self.repeat_text(row["recurrence"]),
            "alarm": bool(row["alarm"]),
            "conversation_id": row["conversation_id"],
            "next_run": row["due_at"],                          # UTC, like the db
            "next_run_local": due.strftime("%a %d %b %H:%M"),
            "when": due.strftime("%Y-%m-%d %H:%M"),             # editable, parse_when reads it back
            "timezone": str(tz),
        }

    @staticmethod
    def describe(task: dict, with_contact: bool = False) -> str:
        """one line of a task for the model or a log"""
        contact = f" ({task['contact_name']})" if with_contact and task.get("contact_name") else ""
        alarm = ", alarm" if task["alarm"] else ""
        return f"#{task['id']}{contact} {task['repeat_text']}, next {task['next_run_local']}{alarm}: {task['task']}"
