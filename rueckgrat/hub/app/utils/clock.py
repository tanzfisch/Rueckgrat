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

def next_daily(due: datetime, tz: ZoneInfo, now: datetime) -> datetime:
    """the next time after now at due's local wall clock time (stays 07:30 across DST changes)"""
    local = due.astimezone(tz)
    day = local.date()
    while True:
        day += timedelta(days=1)
        candidate = at_local(day, local.time(), tz)
        if candidate > now:
            return candidate

def last_occurrence(due: datetime, tz: ZoneInfo, now: datetime) -> datetime:
    """the latest firing of a daily row due at due (<= now): at due's local wall clock time, today or yesterday"""
    at = due.astimezone(tz).time()
    local = now.astimezone(tz)
    occurrence = at_local(local.date(), at, tz)
    if occurrence > now:
        occurrence = at_local(local.date() - timedelta(days=1), at, tz)
    return max(occurrence, due)

def parse_hhmm(text) -> time | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text or ""))
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    return time(int(match[1]), int(match[2]))
