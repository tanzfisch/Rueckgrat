from typing import Dict,  Any
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from .tool import Tool
from . import prompts
from .current_time_tool import call_timezone

from app.common import get_logger, MessageQueue
logger = get_logger()

MAX_DAYS = 365 * 1000


class DateCalcError(Exception):
    pass


def _parse_date(text, zone: ZoneInfo) -> date:
    """YYYY-MM-DD, or "today" in zone"""
    text = str(text).strip().lower()
    if text in ("today", "now", ""):
        return datetime.now(zone).date()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise DateCalcError(f"invalid date '{text}', expected YYYY-MM-DD or 'today'")


def _show(d: date) -> str:
    return f"{d.isoformat()} ({d.strftime('%A')})"


def date_calc(start, end=None, days=None, zone: ZoneInfo = ZoneInfo("UTC")) -> str:
    """'end' given: days between start and end. 'days' given: start plus days (negative goes back). zone: whose today"""
    start_date = _parse_date(start, zone)

    if end is not None:
        end_date = _parse_date(end, zone)
        delta = (end_date - start_date).days
        weeks, rest = divmod(abs(delta), 7)
        return f"from {_show(start_date)} to {_show(end_date)}: {delta} days ({weeks} weeks {rest} days)"

    if days is not None:
        try:
            offset = int(float(days))
        except (TypeError, ValueError):
            raise DateCalcError(f"invalid number of days '{days}'")
        if abs(offset) > MAX_DAYS:
            raise DateCalcError("number of days too large")
        try:
            result_date = start_date + timedelta(days=offset)
        except OverflowError:
            raise DateCalcError("resulting date out of range")
        sign = "+" if offset >= 0 else "-"
        return f"{_show(start_date)} {sign} {abs(offset)} days = {_show(result_date)}"

    raise DateCalcError("needs either 'end' or 'days'")


class DateCalcTool(Tool):
    description = prompts.DATE_CALC_DESCRIPTION
    thresholds = (0.55, 0.6)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user ask how many days, weeks or months are left until something or have passed since something?",
        "Does the user ask what day of the week a date is?",
        "Does the user ask how long it is until or since a date, a birthday or a holiday?",
        "Does the user ask what date it is a number of days from today?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "date_calc"

    def execute(self) -> None:
        if not "start" in self.tool_call:
            logger.error("invalid date_calc")
            return None

        MessageQueue().send_status_message("calculating dates")

        try:
            zone, note = call_timezone(self.tool_call.get("timezone"), self.db, self.get_user_id())
            text = date_calc(
                start=self.tool_call["start"],
                end=self.tool_call.get("end"),
                days=self.tool_call.get("days"),
                zone=zone
            )
            today_used = any(str(self.tool_call.get(key)).strip().lower() in ("today", "now", "") for key in ("start", "end") if key in self.tool_call)
            result = {"tool": self.name(), "text": text + (note if today_used else "")}
        except DateCalcError as e:
            logger.warning(f"date_calc failed: {e}")
            result = {"tool": self.name(), "error": str(e)}
        except Exception as e:
            logger.error(f"failed to calculate dates {repr(e)}")
            result = {"tool": self.name(), "error": "date calculation failed"}

        self.add_result(result)

    @classmethod
    def prompt(cls) -> str:
        return prompts.DATE_CALC_PROMPT
