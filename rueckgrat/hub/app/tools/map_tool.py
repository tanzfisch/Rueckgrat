import math
import time
import threading
from pathlib import Path
from collections import OrderedDict
from typing import Dict, Any, Optional
import requests
from .tool import Tool
from . import prompts
from app.utils.library import Library, LibraryError
import re

from app.common import get_logger, MessageQueue
logger = get_logger()

# openstreetmap: nominatim geocodes the place text, the hub proxies the map tiles for the client, both ask for an
# identifying user agent (library defaults get blocked), nominatim at most 1 request per second, tiles cached >= 7 days
USER_AGENT = "Rueckgrat/1.0 (self-hosted personal assistant)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
OPEN_METEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_DIR = Path("/hub/images/map_tiles")
OFFLINE_TILE_DIR = TILE_DIR / "offline"     # the tiles the hub drew from NOMAD's map files, apart from the osm ones
TILE_MAX_AGE = 7 * 24 * 3600
MAX_ZOOM = 16
MAP_TIMEOUT = 10
MAX_QUERY_LENGTH = 200
MAX_LABEL_LENGTH = 80
GEOCODE_CACHE_SIZE = 128

_geocode_lock = threading.Lock()
_last_request: Dict[str, float] = {}    # per service, each gets at most 1 request per second
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

def _parse_address(query: str) -> Dict[str, str]:
    """Very simple structured split. Not perfect, but catches common cases."""
    parts = [p.strip() for p in query.split(",") if p.strip()]
    params = {}
    postal = None
    for i, p in enumerate(parts):
        if re.fullmatch(r"\d{4,6}", p) or re.fullmatch(r"\d{5}", p):
            postal = p
            parts.pop(i)
            break
    if postal:
        params["postalcode"] = postal
    if parts:
        # last = country, second last = city (heuristic)
        if len(parts) >= 2:
            params["country"] = parts[-1]
            params["city"] = parts[-2]
            street_parts = parts[:-2]
        else:
            params["city"] = parts[-1]
            street_parts = parts[:-1]
        if street_parts:
            params["street"] = " ".join(street_parts)
    return params

# zoom for a place without a bounding box, by its photon type
PHOTON_ZOOM = {"house": MAX_ZOOM, "street": 16, "locality": 15, "district": 14, "city": 12, "county": 10, "state": 7, "country": 5}


def _request(url: str, params: dict) -> Any:
    """one get, rate limited per service, raises on network and http errors"""
    time.sleep(max(0.0, _last_request.get(url, 0.0) + 1.0 - time.monotonic()))
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=MAP_TIMEOUT)
    finally:
        _last_request[url] = time.monotonic()
    resp.raise_for_status()
    return resp.json()

def _place(lat, lon, display_name: str, zoom: int) -> Dict[str, Any]:
    return {"lat": float(lat), "lon": float(lon), "display_name": display_name, "zoom": zoom}

def _nominatim(query: str) -> Optional[Dict[str, Any]]:
    def search(params: dict) -> list:
        return _request(NOMINATIM_URL, {**params, "format": "jsonv2", "limit": 1})

    # 1. free-form
    places = search({"q": query})
    # 2. drop first comma part (often a landmark)
    if not places and "," in query:
        places = search({"q": query.split(",", 1)[1].strip()})
    # 3. structured
    if not places:
        structured = _parse_address(query)
        if structured:
            places = search(structured)
    if not places:
        return None
    p = places[0]
    return _place(p["lat"], p["lon"], p.get("display_name") or query, _zoom(p))

def _photon(query: str) -> Optional[Dict[str, Any]]:
    features = (_request(PHOTON_URL, {"q": query, "limit": 1}) or {}).get("features") or []
    if not features:
        return None
    props = features[0].get("properties") or {}
    lon, lat = features[0]["geometry"]["coordinates"][:2]
    extent = props.get("extent")    # [west, north, east, south]
    if extent and len(extent) == 4:
        zoom = _zoom({"boundingbox": [extent[3], extent[1], extent[0], extent[2]]})
    else:
        zoom = PHOTON_ZOOM.get(props.get("type"), 15)
    name_parts = [props.get("name"), " ".join(filter(None, [props.get("housenumber"), props.get("street")])),
                  props.get("city"), props.get("state"), props.get("country")]
    display_name = ", ".join(dict.fromkeys(p for p in name_parts if p)) or query
    return _place(lat, lon, display_name, zoom)

def _open_meteo(query: str) -> Optional[Dict[str, Any]]:
    """only knows place names: the whole query, then each comma part from the end but the country (the city mostly)"""
    parts = [p.strip() for p in query.split(",") if p.strip()]
    names = [query] + (parts[-2::-1] if len(parts) > 1 else [])
    for name in names:
        results = (_request(OPEN_METEO_URL, {"name": name, "count": 1, "format": "json"}) or {}).get("results") or []
        if results:
            r = results[0]
            code = r.get("feature_code") or ""
            zoom = 5 if code.startswith("PCL") else 8 if code.startswith("ADM") else 12
            display_name = ", ".join(dict.fromkeys(p for p in [r.get("name"), r.get("admin1"), r.get("country")] if p))
            return _place(r["latitude"], r["longitude"], display_name or query, zoom)
    return None

GEOCODERS = [("nominatim", _nominatim), ("photon", _photon), ("open-meteo", _open_meteo)]

# zoom of a place found offline by the decimals of its Wikipedia coordinates (how exact they are): a country has none,
# a region 1-2, a city or a mountain 4-5 (degrees, minutes, seconds), a building 6 or more
DECIMALS_ZOOM = {0: 5, 1: 8, 2: 10, 3: 12, 4: 13, 5: 13}


def geocode_offline(query: str, library: Library) -> Optional[Dict[str, Any]]:
    """the place from the offline library's Wikipedia: the article about query and its coordinates, None without them.
    raises LibraryError when the library does not answer"""
    book = library.wikipedia_book("en")
    if book is None:
        return None
    candidates = [query] + ([query.split(",", 1)[0].strip()] if "," in query else [])
    for candidate in candidates:     # "Sky Tower, Victoria Street West, Auckland": the whole text, then its first part
        article = library.lookup(book["id"], candidate)
        coordinates = Library.coordinates(article["html"]) if article else None
        if coordinates:
            lat, lon, decimals = coordinates
            return _place(lat, lon, article["title"], DECIMALS_ZOOM.get(decimals, MAX_ZOOM - 1))
    return None


def geocode(query: str) -> Optional[Dict[str, Any]]:
    """{"lat", "lon", "display_name", "zoom"} of the first service with a match: nominatim, photon, open-meteo.
    None if all of them answered without a match. raises when none matched and one failed, so a failure is not cached"""
    key = query.lower()
    with _geocode_lock:
        if key in _geocode_cache:
            _geocode_cache.move_to_end(key)
            return _geocode_cache[key]

        place, error = None, None
        for service, lookup in GEOCODERS:
            try:
                place = lookup(query)
            except Exception as e:
                logger.warning(f"geocoding '{query}' with {service} failed: {e!r}")
                error = e
                continue
            if place:
                if service != GEOCODERS[0][0]:
                    logger.info(f"geocoded '{query}' with fallback {service}")
                break

        if not place and error:
            raise error
        _geocode_cache[key] = place
        if len(_geocode_cache) > GEOCODE_CACHE_SIZE:
            _geocode_cache.popitem(last=False)
        return place


def get_tile(z: int, x: int, y: int, infrastructure=None) -> Optional[bytes]:
    """png bytes of one map tile: osm while the internet is there (infrastructure.available), drawn from NOMAD's map files
    without it or when osm has none. None when neither has it"""
    if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    online = infrastructure is None or infrastructure.available("internet")
    tile = _osm_tile(z, x, y) if online else None
    if tile is None and infrastructure is not None and infrastructure.available("offline_map"):
        tile = _offline_tile(z, x, y, infrastructure.nomad().offline_map())
    return tile


def _offline_tile(z: int, x: int, y: int, offline_map) -> Optional[bytes]:
    """a tile drawn from NOMAD's map files, cached like the osm tiles (TILE_MAX_AGE)"""
    path = OFFLINE_TILE_DIR / str(z) / str(x) / f"{y}.png"
    if path.is_file() and time.time() - path.stat().st_mtime < TILE_MAX_AGE:
        return path.read_bytes()
    try:
        tile = offline_map.render(z, x, y)
    except Exception as e:
        logger.error(f"offline map tile {z}/{x}/{y} - {e!r}")
        tile = None
    if tile is None:
        return path.read_bytes() if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tile)
    return tile


def _osm_tile(z: int, x: int, y: int) -> Optional[bytes]:
    """png bytes of one osm tile, from the cache if it's younger than TILE_MAX_AGE, else downloaded (an old copy if that fails)"""
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
    description = prompts.MAP_DESCRIPTION
    requires_any = ("internet", "offline_map")  # geocoding and tiles online, else NOMAD's map and its library's coordinates
    thresholds = (0.45, 0.5)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    question = [
        "Does the user ask how to get to a place?",
        "Does the user want to see a map?",
        "Does the user ask where a place is on a map?",
    ]

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "show_map"

    def execute(self) -> None:
        query = " ".join(str(self.tool_call.get("address") or "").split())[:MAX_QUERY_LENGTH]
        label = " ".join(str(self.tool_call.get("label") or "").split())[:MAX_LABEL_LENGTH]
        if not query:
            logger.error(f"can't show map")
            return
        
        MessageQueue().send_status_message("looking up the map")

        online = self.infrastructure is None or self.infrastructure.available("internet")
        place = None
        if online:
            try:
                place = geocode(query)
            except Exception as e:
                logger.error(f"geocoding '{query}' failed: {e}")
        nomad = self.infrastructure.nomad() if self.infrastructure is not None else None
        library = nomad.library() if nomad is not None else None
        if place is None and library is not None:
            try:
                place = geocode_offline(query, library)
                if place:
                    logger.info(f"geocoded '{query}' with the offline library")
            except LibraryError as e:
                logger.error(f"offline geocoding '{query}' failed: {e}")

        if place is None:
            logger.error(f"can't find place in map")
            return
        
        place = {"query": query, "label": label, **place}
        if not online and nomad is not None and nomad.url():
            place["link"] = nomad.map_link(place["lat"], place["lon"], place["zoom"])     # the tap opens NOMAD's map
        self.show_data("map", place)
        self.add_result({"tool": self.name(), "text": self._text(place["display_name"]), "place": place})

    def planned_text(self) -> str:
        query = " ".join(str(self.tool_call.get("address") or "").split())[:MAX_QUERY_LENGTH]
        if not query:
            return prompts.MAP_NO_ADDRESS_PART
        return prompts.MAP_LOOKING_UP_PART.format(query=query)

    @staticmethod
    def _text(name: str) -> str:
        return prompts.MAP_SHOWN_PART.format(name=name)

    @classmethod
    def prompt(cls) -> str:
        return prompts.MAP_PROMPT
