from typing import Dict,  Any
from datetime import date, datetime, timedelta
from .tool import Tool, ToolCategory
from .current_time_tool import resolve_timezone

from app.common import get_logger, MessageQueue
logger = get_logger()

MAX_DAYS = 365 * 1000


class DateCalcError(Exception):
    pass


def _parse_date(text, timezone) -> date:
    text = str(text).strip().lower()
    if text in ("today", "now", ""):
        zone = resolve_timezone(timezone)
        if zone is None:
            raise DateCalcError(f"unknown time zone or city '{timezone}'")
        return datetime.now(zone).date()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise DateCalcError(f"invalid date '{text}', expected YYYY-MM-DD or 'today'")


def _show(d: date) -> str:
    return f"{d.isoformat()} ({d.strftime('%A')})"


def date_calc(start, end=None, days=None, timezone="UTC") -> str:
    """'end' given: days between start and end. 'days' given: start plus days (negative goes back)"""
    start_date = _parse_date(start, timezone)

    if end is not None:
        end_date = _parse_date(end, timezone)
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
    category = ToolCategory.TIME
    description = "days between two dates, or a date plus/minus a number of days"
    question = "Does the user want to work something out with dates?"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "date_calc"

    def execute(self) -> None:
        if not "start" in self.tool_call:
            logger.error("invalid date_calc")
            return None

        MessageQueue().send_status_message("calculating dates")

        try:
            text = date_calc(
                start=self.tool_call["start"],
                end=self.tool_call.get("end"),
                days=self.tool_call.get("days"),
                timezone=self.tool_call.get("timezone", "UTC")
            )
            result = {"tool": self.name(), "text": text}
        except DateCalcError as e:
            logger.warning(f"date_calc failed: {e}")
            result = {"tool": self.name(), "error": str(e)}
        except Exception as e:
            logger.error(f"failed to calculate dates {repr(e)}")
            result = {"tool": self.name(), "error": "date calculation failed"}

        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
DATE CALCULATION:
Use for days between two dates or a date plus/minus a number of days. Dates are YYYY-MM-DD or "today".

Parameters:
- start (string, required): start date
- end (string, optional): end date (for difference)
- days (number, optional): number of days to add/subtract
- timezone (string, required): IANA name or city

Example (difference):
{"tool": "date_calc", "start": "today", "end": "2026-12-25", "timezone": "Pacific/Auckland"}

Example (offset):
{"tool": "date_calc", "start": "today", "days": 90, "timezone": "Pacific/Auckland"}
"""
