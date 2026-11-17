import os
import re
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.common import get_logger
logger = get_logger()

# users without a timezone setting (PUT /users/me/timezone) whose app sent none either (/login, /refresh)
DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "UTC")

DB_FORMAT = "%Y-%m-%d %H:%M:%S"   # like sqlite's CURRENT_TIMESTAMP, UTC

def now() -> datetime:
    """the hub's now, UTC"""
    return datetime.now(timezone.utc)

def to_db(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(DB_FORMAT)

def from_db(text: str) -> datetime:
    return datetime.strptime(text, DB_FORMAT).replace(tzinfo=timezone.utc)

def user_timezone_name(db, user_id: int) -> tuple[str, str]:
    """(IANA name, source) of the user's timezone: the one they chose ("setting"), else their device's ("device"),
    else DEFAULT_TIMEZONE ("default")"""
    for source, name in (("setting", db.get_user_timezone(user_id)), ("device", db.get_device_timezone(user_id))):
        if name:
            return name, source
    return DEFAULT_TIMEZONE, "default"

def valid_timezone(name: str) -> bool:
    """an IANA name zoneinfo knows, e.g. Pacific/Auckland"""
    try:
        return bool(name) and ZoneInfo(name) is not None
    except Exception:
        return False

def user_timezone(db, user_id: int) -> ZoneInfo:
    name, _ = user_timezone_name(db, user_id)
    try:
        return ZoneInfo(name)
    except Exception:
        logger.error(f"unknown timezone {name} of user {user_id}, using UTC")
        return ZoneInfo("UTC")

def local_day(local: datetime) -> tuple[str, str]:
    """the user's local day of local as UTC db bounds [start, end)"""
    start = datetime.combine(local.date(), time(0), local.tzinfo)
    end = datetime.combine(local.date() + timedelta(days=1), time(0), local.tzinfo)
    return to_db(start), to_db(end)

def at_local(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tz)

# a calendar row's recurrence (companion_calendar.recurrence): "" once, "daily", "weekdays" (Mon-Fri), "weekly" (due's
# weekday) at due's local wall clock time, or "minutes:N" every N minutes from due on
RECURRENCES = ("", "daily", "weekdays", "weekly")
EVERY_PREFIX = "minutes:"

def every_minutes(recurrence: str) -> int | None:
    """N of "minutes:N", None for the other recurrences"""
    if not str(recurrence or "").startswith(EVERY_PREFIX):
        return None
    try:
        minutes = int(recurrence[len(EVERY_PREFIX):])
    except ValueError:
        return None
    return minutes if minutes > 0 else None

def valid_recurrence(recurrence: str) -> bool:
    return recurrence in RECURRENCES or every_minutes(recurrence) is not None

def _on_day(recurrence: str, day: date, first: date) -> bool:
    """day is one of a wall clock recurrence's days (first: the day of its first occurrence)"""
    if recurrence == "weekdays":
        return day.weekday() < 5
    if recurrence == "weekly":
        return day.weekday() == first.weekday()
    return True

def next_occurrence(due: datetime, recurrence: str, tz: ZoneInfo, now: datetime) -> datetime:
    """the first occurrence of a recurring row after now (at due's local wall clock time, stays 07:30 across DST changes,
    every N minutes: due + k * N). ValueError for "" or an unknown recurrence"""
    minutes = every_minutes(recurrence)
    if minutes is not None:
        step = timedelta(minutes=minutes)
        return due + step * (max(0, (now - due) // step) + 1)
    if recurrence not in RECURRENCES[1:]:
        raise ValueError(f"no recurrence: {recurrence!r}")
    local = due.astimezone(tz)
    day = max(local.date(), now.astimezone(tz).date() - timedelta(days=8))    # after a long downtime: not from the first day on
    while True:
        day += timedelta(days=1)
        candidate = at_local(day, local.time(), tz)
        if candidate > now and _on_day(recurrence, day, local.date()):
            return candidate

def last_occurrence(due: datetime, tz: ZoneInfo, now: datetime, recurrence: str = "daily") -> datetime:
    """the latest firing of a recurring row due at due (<= now, never before due): at due's local wall clock time on the
    last of its days, every N minutes: due + k * N"""
    minutes = every_minutes(recurrence)
    if minutes is not None:
        step = timedelta(minutes=minutes)
        return due + step * max(0, (now - due) // step)
    local_due = due.astimezone(tz)
    day = now.astimezone(tz).date()
    for _ in range(8):
        occurrence = at_local(day, local_due.time(), tz)
        if occurrence <= now and _on_day(recurrence, day, local_due.date()):
            return max(occurrence, due)
        day -= timedelta(days=1)
    return due

def first_occurrence(start: datetime, recurrence: str, tz: ZoneInfo) -> datetime:
    """the first firing of a new row asked for start: start itself, a wall clock recurrence moves it to the first of its
    days at start's local time (weekdays: a Saturday start fires on Monday)"""
    if recurrence not in ("weekdays",):
        return start
    local = start.astimezone(tz)
    day = local.date()
    while not _on_day(recurrence, day, local.date()):
        day += timedelta(days=1)
    return at_local(day, local.time(), tz)

def parse_hhmm(text) -> time | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text or ""))
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    return time(int(match[1]), int(match[2]))
