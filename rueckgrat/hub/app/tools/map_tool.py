import math
import shutil
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
TILE_MAX_AGE = 7 * 24 * 3600
MAX_ZOOM = 16
MAP_TIMEOUT = 10
MAX_QUERY_LENGTH = 200
MAX_LABEL_LENGTH = 80
GEOCODE_CACHE_SIZE = 128
# a short "where is X" / "where's X": too short for the laya questions (they skip messages of a few words), text_score
# makes the map mandatory. Not when X is a pronoun or possessive ("where is it", "where's my phone"), nor "the" + a lower
# case word ("where's the bug"), "the Louvre" is a place
SHORT_WHERE = re.compile(r"^\s*where(?:'s|\u2019s|\s+is|\s+are)\s+(?P<place>[^\s?!.]+(?:\s+[^\s?!.]+){0,2})\s*[?!.]*\s*$", re.IGNORECASE)
NOT_PLACES = frozenset("i me my mine you your yours we us our ours he him his she her hers it its they them their theirs "
                       "this that these those there here everyone everybody someone somebody something a an".split())
WHERE_SCORE = 0.6   # above the mandatory threshold

# zoom for a place without a bounding box, by its photon type
PHOTON_ZOOM = {"house": MAX_ZOOM, "street": 16, "locality": 15, "district": 14, "city": 12, "county": 10, "state": 7, "country": 5}
# zoom of a place found offline by the decimals of its Wikipedia coordinates (how exact they are): a country has none,
# a region 1-2, a city or a mountain 4-5 (degrees, minutes, seconds), a building 6 or more
DECIMALS_ZOOM = {0: 5, 1: 8, 2: 10, 3: 12, 4: 13, 5: 13}


class Geocoder:
    """the place of a text: online nominatim, photon, open-meteo (each at most 1 request per second, the answers cached),
    offline the library's Wikipedia coordinates. One shared by the map tools (MapTool._geocoder)"""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_request: Dict[str, float] = {}   # per service url
        self._cache: OrderedDict = OrderedDict()    # lower case query -> place or None, at most GEOCODE_CACHE_SIZE
        self._services = [("nominatim", self._nominatim), ("photon", self._photon), ("open-meteo", self._open_meteo)]

    def geocode(self, query: str) -> Optional[Dict[str, Any]]:
        """{"lat", "lon", "display_name", "zoom"} of the first service with a match: nominatim, photon, open-meteo.
        None if all of them answered without a match. raises when none matched and one failed, so a failure is not cached"""
        key = query.lower()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

            place, error = None, None
            for service, lookup in self._services:
                try:
                    place = lookup(query)
                except Exception as e:
                    logger.warning(f"geocoding '{query}' with {service} failed: {e!r}")
                    error = e
                    continue
                if place:
                    if service != self._services[0][0]:
                        logger.info(f"geocoded '{query}' with fallback {service}")
                    break

            if not place and error:
                raise error
            self._cache[key] = place
            if len(self._cache) > GEOCODE_CACHE_SIZE:
                self._cache.popitem(last=False)
            return place

    def geocode_offline(self, query: str, library: Library) -> Optional[Dict[str, Any]]:
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
                return self._place(lat, lon, article["title"], DECIMALS_ZOOM.get(decimals, MAX_ZOOM - 1))
        return None

    def _request(self, url: str, params: dict) -> Any:
        """one get, rate limited per service, raises on network and http errors"""
        time.sleep(max(0.0, self._last_request.get(url, 0.0) + 1.0 - time.monotonic()))
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=MAP_TIMEOUT)
        finally:
            self._last_request[url] = time.monotonic()
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _zoom(place: Dict[str, Any]) -> int:
        """zoom that fits the place's bounding box into the map bubble (about 1.5 tiles wide), a street or building gets MAX_ZOOM"""
        try:
            south, north, west, east = (float(v) for v in place["boundingbox"])
            span = max(east - west, (north - south) * 1.5, 1e-6)
            return max(3, min(MAX_ZOOM, int(math.log2(360 / span)) + 1))
        except (KeyError, ValueError, TypeError):
            return 15

    @staticmethod
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

    @staticmethod
    def _place(lat, lon, display_name: str, zoom: int) -> Dict[str, Any]:
        return {"lat": float(lat), "lon": float(lon), "display_name": display_name, "zoom": zoom}

    def _nominatim(self, query: str) -> Optional[Dict[str, Any]]:
        def search(params: dict) -> list:
            return self._request(NOMINATIM_URL, {**params, "format": "jsonv2", "limit": 1})

        # 1. free-form
        places = search({"q": query})
        # 2. drop first comma part (often a landmark)
        if not places and "," in query:
            places = search({"q": query.split(",", 1)[1].strip()})
        # 3. structured
        if not places:
            structured = self._parse_address(query)
            if structured:
                places = search(structured)
        if not places:
            return None
        p = places[0]
        return self._place(p["lat"], p["lon"], p.get("display_name") or query, self._zoom(p))

    def _photon(self, query: str) -> Optional[Dict[str, Any]]:
        features = (self._request(PHOTON_URL, {"q": query, "limit": 1}) or {}).get("features") or []
        if not features:
            return None
        props = features[0].get("properties") or {}
        lon, lat = features[0]["geometry"]["coordinates"][:2]
        extent = props.get("extent")    # [west, north, east, south]
        if extent and len(extent) == 4:
            zoom = self._zoom({"boundingbox": [extent[3], extent[1], extent[0], extent[2]]})
        else:
            zoom = PHOTON_ZOOM.get(props.get("type"), 15)
        name_parts = [props.get("name"), " ".join(filter(None, [props.get("housenumber"), props.get("street")])),
                      props.get("city"), props.get("state"), props.get("country")]
        display_name = ", ".join(dict.fromkeys(p for p in name_parts if p)) or query
        return self._place(lat, lon, display_name, zoom)

    def _open_meteo(self, query: str) -> Optional[Dict[str, Any]]:
        """only knows place names: the whole query, then each comma part from the end but the country (the city mostly)"""
        parts = [p.strip() for p in query.split(",") if p.strip()]
        names = [query] + (parts[-2::-1] if len(parts) > 1 else [])
        for name in names:
            results = (self._request(OPEN_METEO_URL, {"name": name, "count": 1, "format": "json"}) or {}).get("results") or []
            if results:
                r = results[0]
                code = r.get("feature_code") or ""
                zoom = 5 if code.startswith("PCL") else 8 if code.startswith("ADM") else 12
                display_name = ", ".join(dict.fromkeys(p for p in [r.get("name"), r.get("admin1"), r.get("country")] if p))
                return self._place(r["latitude"], r["longitude"], display_name or query, zoom)
        return None


class MapTiles:
    """the map bubble's 256 px png tiles, cached on disk for TILE_MAX_AGE: osm ones in the tile folder while the internet is
    there, else the ones drawn from NOMAD's map files in its offline folder. One per hub (app.state.map_tiles)"""

    def __init__(self, infrastructure, directory: Path = TILE_DIR):
        self._infrastructure = infrastructure
        self._dir = directory
        self._offline_dir = directory / "offline"     # the tiles drawn from NOMAD's map files, apart from the osm ones
        self._slots = threading.Semaphore(2)          # the tile policy allows 2 parallel downloads

    def tile(self, z: int, x: int, y: int) -> Optional[bytes]:
        """png bytes of one map tile: osm while the internet is there, drawn from NOMAD's map files without it or when osm
        has none. None when neither has it"""
        if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
            return None
        tile = self._osm(z, x, y) if self._infrastructure.available("internet") else None
        if tile is None and self._infrastructure.available("offline_map"):
            tile = self._offline(z, x, y)
        return tile

    def clear_offline(self) -> None:
        """empties the offline folder on hub start: a new hub may draw the tiles differently (fonts, style). The osm tiles
        stay, _offline makes the folders again"""
        if not self._offline_dir.is_dir():
            return
        count = sum(1 for _ in self._offline_dir.rglob("*.png"))
        try:
            shutil.rmtree(self._offline_dir)
        except OSError as e:
            logger.error(f"offline map tiles not cleared - {e!r}")
            return
        logger.info(f"{count} offline map tile(s) of the last hub cleared")

    @staticmethod
    def _path(directory: Path, z: int, x: int, y: int) -> Path:
        return directory / str(z) / str(x) / f"{y}.png"

    @staticmethod
    def _fresh(path: Path) -> Optional[bytes]:
        """the cached tile if it's younger than TILE_MAX_AGE"""
        if path.is_file() and time.time() - path.stat().st_mtime < TILE_MAX_AGE:
            return path.read_bytes()
        return None

    @staticmethod
    def _store(path: Path, tile: bytes) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tile)
        return tile

    def _offline(self, z: int, x: int, y: int) -> Optional[bytes]:
        """a tile drawn from NOMAD's map files, cached, an old copy if drawing fails"""
        path = self._path(self._offline_dir, z, x, y)
        cached = self._fresh(path)
        if cached is not None:
            return cached
        try:
            tile = self._infrastructure.nomad().offline_map().render(z, x, y)
        except Exception as e:
            logger.error(f"offline map tile {z}/{x}/{y} - {e!r}")
            tile = None
        if tile is None:
            return path.read_bytes() if path.is_file() else None
        return self._store(path, tile)

    def _osm(self, z: int, x: int, y: int) -> Optional[bytes]:
        """one osm tile, cached, else downloaded (an old copy if that fails)"""
        path = self._path(self._dir, z, x, y)
        cached = self._fresh(path)
        if cached is not None:
            return cached
        try:
            with self._slots:
                resp = requests.get(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT}, timeout=MAP_TIMEOUT)
            resp.raise_for_status()
            return self._store(path, resp.content)
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
        "Is the user asking where a place is, not facts about it like its capital, size, height or population?",
    ]

    _geocoder = Geocoder()      # shared by all map tool calls: its rate limits and cache

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def text_score(cls, prompt: str) -> float:
        """WHERE_SCORE for a short question where a place is (SHORT_WHERE), else 0.0"""
        match = SHORT_WHERE.match(prompt or "")
        if not match:
            return 0.0
        words = match.group("place").split()
        if words[0].lower() in NOT_PLACES:
            return 0.0
        if words[0].lower() == "the" and (len(words) == 1 or not words[1][:1].isupper()):
            return 0.0
        return WHERE_SCORE

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
                place = self._geocoder.geocode(query)
            except Exception as e:
                logger.error(f"geocoding '{query}' failed: {e}")
        nomad = self.infrastructure.nomad() if self.infrastructure is not None else None
        library = nomad.library() if nomad is not None else None
        if place is None and library is not None:
            try:
                place = self._geocoder.geocode_offline(query, library)
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
