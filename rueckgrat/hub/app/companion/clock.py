import os
import re
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.common import get_logger
logger = get_logger()

# users without a timezone setting (PUT /users/me/timezone)
DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "UTC")

DB_FORMAT = "%Y-%m-%d %H:%M:%S"   # like sqlite's CURRENT_TIMESTAMP, UTC

# testing only: the companion's clock runs TIME_SCALE times faster (720 = a day in 2 minutes),
# from TIME_START ("2026-10-29T23:50+13:00", no offset = UTC) or from the hub start. unset = real time
TIME_SCALE = float(os.environ.get("COMPANION_TIME_SCALE") or 1)
TIME_START = os.environ.get("COMPANION_TIME_START")
_REAL_START = datetime.now(timezone.utc)
_START = datetime.fromisoformat(TIME_START) if TIME_START else _REAL_START
_START = _START if _START.tzinfo else _START.replace(tzinfo=timezone.utc)
if TIME_SCALE != 1 or TIME_START:
    logger.warning(f"companion clock simulated: x{TIME_SCALE} from {_START.isoformat()}")

def now() -> datetime:
    """the companion's now, UTC"""
    real = datetime.now(timezone.utc)
    if TIME_SCALE == 1 and not TIME_START:
        return real
    return _START + (real - _REAL_START) * TIME_SCALE

def real_seconds(seconds: float) -> float:
    """how long companion seconds take on the wall clock"""
    return seconds / TIME_SCALE

def to_db(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(DB_FORMAT)

def from_db(text: str) -> datetime:
    return datetime.strptime(text, DB_FORMAT).replace(tzinfo=timezone.utc)

def user_timezone(db, user_id: int) -> ZoneInfo:
    name = db.get_user_timezone(user_id) or DEFAULT_TIMEZONE
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
