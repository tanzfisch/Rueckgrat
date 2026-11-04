import math
import time
import threading
from pathlib import Path
from collections import OrderedDict
from typing import Dict, Any, Optional
import requests
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
logger = get_logger()

# openstreetmap: nominatim geocodes the place text, the hub proxies the map tiles for the client, both ask for an
# identifying user agent (library defaults get blocked), nominatim at most 1 request per second, tiles cached >= 7 days
USER_AGENT = "Rueckgrat/1.0 (self-hosted personal assistant)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_DIR = Path("/hub/images/map_tiles")
TILE_MAX_AGE = 7 * 24 * 3600
MAX_ZOOM = 16
MAP_TIMEOUT = 10
MAX_QUERY_LENGTH = 200
MAX_LABEL_LENGTH = 80
GEOCODE_CACHE_SIZE = 128

_geocode_lock = threading.Lock()
_last_geocode = 0.0
_geocode_cache: OrderedDict = OrderedDict()
_tile_slots = threading.Semaphore(2)    # the tile policy allows 2 parallel downloads


def _zoom(place: Dict[str, Any]) -> int:
    """zoom that fits the place's bounding box into the map bubble (about 1.5 tiles wide), a street or building gets MAX_ZOOM"""
    try:
        south, north, west, east = (float(v) for v in place["boundingbox"])
        span = max(east - west, (north - south) * 1.5, 1e-6)
        return max(3, min(MAX_ZOOM, int(math.log2(360 / span)) + 1))
    except (KeyError, ValueError, TypeError):
        return 15


def geocode(query: str) -> Optional[Dict[str, Any]]:
    """{"lat", "lon", "display_name", "zoom"} of the best nominatim match, None if nothing matches.
    raises on network errors, so a failure is not cached"""
    global _last_geocode
    key = query.lower()
    with _geocode_lock:
        if key in _geocode_cache:
            _geocode_cache.move_to_end(key)
            return _geocode_cache[key]
        time.sleep(max(0.0, _last_geocode + 1.0 - time.monotonic()))
        try:
            resp = requests.get(NOMINATIM_URL, params={"q": query, "format": "jsonv2", "limit": 1},
                                headers={"User-Agent": USER_AGENT}, timeout=MAP_TIMEOUT)
        finally:
            _last_geocode = time.monotonic()
        resp.raise_for_status()
        places = resp.json()
        place = None
        if places:
            p = places[0]
            place = {"lat": float(p["lat"]), "lon": float(p["lon"]), "display_name": p.get("display_name") or query, "zoom": _zoom(p)}
        _geocode_cache[key] = place
        if len(_geocode_cache) > GEOCODE_CACHE_SIZE:
            _geocode_cache.popitem(last=False)
        return place


def get_tile(z: int, x: int, y: int) -> Optional[bytes]:
    """png bytes of one osm tile, from the cache if it's younger than TILE_MAX_AGE, else downloaded (an old copy if that fails)"""
    if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    path = TILE_DIR / str(z) / str(x) / f"{y}.png"
    if path.is_file() and time.time() - path.stat().st_mtime < TILE_MAX_AGE:
        return path.read_bytes()
    try:
        with _tile_slots:
            resp = requests.get(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT}, timeout=MAP_TIMEOUT)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        return resp.content
    except Exception as e:
        logger.error(f"map tile {z}/{x}/{y} - {e}")
        return path.read_bytes() if path.is_file() else None


class MapTool(Tool):
    category = ToolCategory.GENERAL
    description = "shows the user a map bubble of a place or an address, tapping it opens the maps app"
    question = [
        "Does the user ask how to get to a place?",
        "Does the user want to see a map?",
        "Is the user asking for the location of a place?",
        "Does the user ask where exactly a place is?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "show_map"

    def execute(self) -> None:
        query = " ".join(str(self.tool_call.get("address") or "").split())[:MAX_QUERY_LENGTH]
        label = " ".join(str(self.tool_call.get("label") or "").split())[:MAX_LABEL_LENGTH]
        if not query:
            result = {"tool": self.name(), "error": "no map shown, it needs an address or a place"}
        elif "map" in self.response:
            result = {"tool": self.name(), "error": "only one map per message, the first one is shown"}
        else:
            MessageQueue().send_status_message("looking up the map")
            try:
                place = geocode(query)
            except Exception as e:
                logger.error(f"geocoding '{query}' failed: {e}")
                place = None
            if place is None:
                result = {"tool": self.name(), "error": f"no map shown, \"{query}\" was not found. Do not claim to show a map."}
            else:
                self.response["map"] = {"query": query, "label": label, **place}    # MetaTask stores it with the answer message and sends it with the final "chat"
                result = {"tool": self.name(), "text": f"a map of {place['display_name']} is shown to the user, tapping it opens their maps app. "
                          "Do not write coordinates or map links in your answer text, at most one short line that points to the map."}
        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
SHOW_MAP:
Use when the user asks where a place is, how to get there, or wants to see it on a map, or when you suggest going to or meeting at a specific place. The map is shown under your answer, tapping it opens the user's maps app.
Do not use it for places in stories, roleplay or memories, for an address the user only mentions in passing (their home, their office), or for questions about a place that don't need a map (weather, time, history, facts).

Parameters:
- address (string, required): the address or the place, as precise as you know it, with the city
- label (string, optional): a short name for the pin

One map per message. Do not write coordinates or map links in your answer text.

Example:
{"tool": "show_map", "address": "Sky Tower, Victoria Street West, Auckland", "label": "Sky Tower"}
"""
