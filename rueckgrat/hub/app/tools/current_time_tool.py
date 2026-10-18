from typing import Dict,  Any, Optional
import re
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
logger = get_logger()

TIMEZONE_ALIASES = {"utc": "UTC", "gmt": "UTC", "z": "UTC", "zulu": "UTC"}

# well known cities -> IANA zone, mainly the ones whose name is not part of a zone name ("munich", "san francisco").
# keys are lowercase with single spaces, see _city_key() for the normalization of the lookup
CITY_TIMEZONES = {
    # Europe
    "london": "Europe/London", "manchester": "Europe/London", "edinburgh": "Europe/London",
    "dublin": "Europe/Dublin", "lisbon": "Europe/Lisbon", "madrid": "Europe/Madrid", "barcelona": "Europe/Madrid",
    "paris": "Europe/Paris", "brussels": "Europe/Brussels", "amsterdam": "Europe/Amsterdam",
    "berlin": "Europe/Berlin", "munich": "Europe/Berlin", "frankfurt": "Europe/Berlin", "hamburg": "Europe/Berlin",
    "cologne": "Europe/Berlin", "dusseldorf": "Europe/Berlin", "stuttgart": "Europe/Berlin", "offenbach": "Europe/Berlin",
    "zurich": "Europe/Zurich", "geneva": "Europe/Zurich", "vienna": "Europe/Vienna", "prague": "Europe/Prague",
    "warsaw": "Europe/Warsaw", "budapest": "Europe/Budapest", "rome": "Europe/Rome", "milan": "Europe/Rome",
    "athens": "Europe/Athens", "istanbul": "Europe/Istanbul", "copenhagen": "Europe/Copenhagen",
    "oslo": "Europe/Oslo", "stockholm": "Europe/Stockholm", "helsinki": "Europe/Helsinki",
    "reykjavik": "Atlantic/Reykjavik", "kyiv": "Europe/Kyiv", "moscow": "Europe/Moscow",
    "st petersburg": "Europe/Moscow",
    # North America
    "new york": "America/New_York", "washington": "America/New_York", "boston": "America/New_York",
    "philadelphia": "America/New_York", "miami": "America/New_York", "atlanta": "America/New_York",
    "chicago": "America/Chicago", "dallas": "America/Chicago", "houston": "America/Chicago",
    "denver": "America/Denver", "phoenix": "America/Phoenix", "las vegas": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles", "san francisco": "America/Los_Angeles", "san diego": "America/Los_Angeles",
    "seattle": "America/Los_Angeles", "anchorage": "America/Anchorage", "honolulu": "Pacific/Honolulu",
    "toronto": "America/Toronto", "montreal": "America/Toronto", "vancouver": "America/Vancouver",
    "calgary": "America/Edmonton", "mexico city": "America/Mexico_City", "havana": "America/Havana",
    # South America
    "sao paulo": "America/Sao_Paulo", "rio de janeiro": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago", "lima": "America/Lima", "bogota": "America/Bogota", "caracas": "America/Caracas",
    # Asia
    "tokyo": "Asia/Tokyo", "osaka": "Asia/Tokyo", "kyoto": "Asia/Tokyo", "seoul": "Asia/Seoul",
    "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "shenzhen": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei", "manila": "Asia/Manila", "singapore": "Asia/Singapore", "kuala lumpur": "Asia/Kuala_Lumpur",
    "jakarta": "Asia/Jakarta", "bangkok": "Asia/Bangkok", "hanoi": "Asia/Ho_Chi_Minh", "ho chi minh city": "Asia/Ho_Chi_Minh",
    "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "bangalore": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata", "chennai": "Asia/Kolkata", "karachi": "Asia/Karachi", "dhaka": "Asia/Dhaka",
    "kathmandu": "Asia/Kathmandu", "colombo": "Asia/Colombo",
    # Middle East
    "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai", "doha": "Asia/Qatar", "riyadh": "Asia/Riyadh",
    "tel aviv": "Asia/Jerusalem", "jerusalem": "Asia/Jerusalem", "tehran": "Asia/Tehran", "baghdad": "Asia/Baghdad",
    # Africa
    "cairo": "Africa/Cairo", "casablanca": "Africa/Casablanca", "lagos": "Africa/Lagos", "accra": "Africa/Accra",
    "addis ababa": "Africa/Addis_Ababa", "nairobi": "Africa/Nairobi", "johannesburg": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    # Oceania
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth", "adelaide": "Australia/Adelaide", "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland", "christchurch": "Pacific/Auckland", "queenstown": "Pacific/Auckland",
    "palmerston north": "Pacific/Auckland", "suva": "Pacific/Fiji",
}
# alternative spellings, endonyms and nicknames -> key in CITY_TIMEZONES
CITY_NAME_ALIASES = {
    "münchen": "munich", "munchen": "munich", "muenchen": "munich", "köln": "cologne", "koln": "cologne",
    "koeln": "cologne", "düsseldorf": "dusseldorf", "duesseldorf": "dusseldorf", "frankfurt am main": "frankfurt",
    "offenbach am main": "offenbach", "zürich": "zurich", "genf": "geneva", "wien": "vienna", "praha": "prague",
    "roma": "rome", "milano": "milan", "lisboa": "lisbon", "kiev": "kyiv", "saint petersburg": "st petersburg",
    "nyc": "new york", "new york city": "new york", "washington dc": "washington", "la": "los angeles",
    "sf": "san francisco", "vegas": "las vegas", "montréal": "montreal", "são paulo": "sao paulo",
    "rio": "rio de janeiro", "bogotá": "bogota", "ciudad de mexico": "mexico city", "cdmx": "mexico city",
    "peking": "beijing", "bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai", "bengaluru": "bangalore",
    "saigon": "ho chi minh city", "palmy": "palmerston north",
}


def _city_key(text: str) -> str:
    """'San Francisco', 'san_francisco', 'san  francisco' and 'St. Petersburg' -> 'san francisco', 'st petersburg'"""
    return re.sub(r"[\s_]+", " ", text.replace(".", "")).strip().lower()


# one flat lookup built at import: cities plus aliases. a zone missing in this tzdata is logged and skipped
_CITY_LOOKUP: Dict[str, str] = {}
for _city, _zone in CITY_TIMEZONES.items():
    if _zone in available_timezones():
        _CITY_LOOKUP[_city] = _zone
    else:
        logger.warning(f"current_time: zone {_zone} of {_city} not in tzdata, skipped")
for _alias, _city in CITY_NAME_ALIASES.items():
    if _city in _CITY_LOOKUP:
        _CITY_LOOKUP[_alias] = _CITY_LOOKUP[_city]
_TIMEZONES = {tz.lower(): tz for tz in available_timezones()}
# "auckland" -> "Pacific/Auckland", "new york" -> "America/New_York" (last part of the IANA name)
_TIMEZONE_CITIES = {}
for _tz in sorted(available_timezones()):
    _TIMEZONE_CITIES.setdefault(_tz.split("/")[-1].lower(), _tz)


def resolve_timezone(text: Optional[str]) -> Optional[ZoneInfo]:
    """alias ("UTC"), known city ("Munich", "nyc"), IANA name ("Europe/Berlin") or last part of an IANA name
    ("new york", "Auckland"), checked in that order. None if unknown"""
    key = _city_key(str(text or "UTC"))
    name = (TIMEZONE_ALIASES.get(key)
            or _CITY_LOOKUP.get(key)
            or _TIMEZONES.get(key.replace(" ", "_"))
            or _TIMEZONE_CITIES.get(key.replace(" ", "_")))
    return ZoneInfo(name) if name else None


def format_time(now: datetime) -> str:
    offset = now.strftime("%z")
    return f"{now.strftime('%A, %d %B %Y, %H:%M')} ({now.tzinfo.key}, UTC{offset[:3]}:{offset[3:]}, {now.tzname()})"


class CurrentTimeTool(Tool):
    category = ToolCategory.TIME
    description = "current date, time and weekday in a city or time zone"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "current_time"

    def execute(self) -> None:
        timezone = self.tool_call.get("timezone", "UTC")
        MessageQueue().send_status_message("checking the time")

        try:
            zone = resolve_timezone(timezone)
            if zone is None:
                result = {"tool": self.name(), "error": f"unknown time zone or city '{timezone}'"}
            else:
                result = {"tool": self.name(), "text": f"current time: {format_time(datetime.now(zone))}"}
        except Exception as e:
            logger.error(f"failed to get current time {repr(e)}")
            result = {"tool": self.name(), "error": "time lookup failed"}

        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
CURRENT TIME:

Use the current_time tool when you need the current date, time or weekday somewhere, e.g. "what time is it in Tokyo". timezone is an IANA name ("Europe/Berlin") or a city ("Auckland", "Munich", "San Francisco"):
{
  "tool": "current_time",
  "timezone": "Pacific/Auckland"
}
"""
