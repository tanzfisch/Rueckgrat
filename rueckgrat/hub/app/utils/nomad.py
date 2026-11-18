"""
Project NOMAD (https://www.projectnomad.us/), an offline knowledge server in the LAN. Optional: its url comes from the hub
settings (hub management) or NOMAD_URL (.env, the installer). Read only GETs, nothing in NOMAD is changed:
  <nomad>/api/system/services       the port of its Information Library (kiwix-serve, nomad_kiwix_server)
  <kiwix>/catalog/v2/entries        answers with a book -> the "library" capability (its books are not kept, see library.py)
  <nomad>/api/maps/regions          the downloaded map regions (.pmtiles)
  <nomad>/pmtiles/world.pmtiles     the world map (zoom 0-5) -> the "offline_map" capability
Never /api/maps/global-map-info (goes to the internet) or /api/maps/styles (may download assets).
probe() runs every INTERNET_PROBE_SECONDS in the hub's capability watcher, a changed url counts from the next probe.
"""
import re
import threading
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

from .library import Library
from .offline_map import OfflineMap, PmtilesArchive
from .url_check import allow_endpoints

from app.common import get_logger
logger = get_logger()

NOMAD_TIMEOUT = 5
KIWIX_SERVICE = "nomad_kiwix_server"
WORLD_MAP = "world.pmtiles"


def normalize_nomad_url(text: str) -> str:
    """"[IP]:8080/home" -> "http://[IP]:8080": scheme added, path dropped. "" stays "" """
    text = str(text or "").strip()
    if not text:
        return ""
    if not re.match(r"https?://", text, re.IGNORECASE):
        text = "http://" + text
    parsed = urlparse(text)
    if not parsed.hostname:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc}"


def endpoint(url: str) -> tuple:
    """(host, port) of a url"""
    parsed = urlparse(url)
    return parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


class Nomad:
    """what the configured NOMAD offers right now. url_source: returns the configured url (HubSettings.get("nomad_url"))"""

    def __init__(self, url_source: Callable[[], str], http_get: Callable = requests.get):
        self._url_source = url_source
        self._get = http_get
        self._lock = threading.Lock()
        self._url = ""
        self._kiwix_url = ""
        self._library: Optional[Library] = None
        self._map: Optional[OfflineMap] = None
        self._state = None      # the last logged (url, library, map)

    def url(self) -> str:
        return self._url

    def configured(self) -> bool:
        return bool(normalize_nomad_url(self._url_source()))

    def kiwix_url(self) -> str:
        return self._kiwix_url

    def library(self) -> Optional[Library]:
        """the library, None when it is not there (not configured, not reachable, no books at the last probe)"""
        return self._library

    def offline_map(self) -> Optional[OfflineMap]:
        return self._map

    def map_link(self, lat: float, lon: float, zoom: int) -> str:
        """NOMAD's own map at a place, the tap target of the map bubble while offline. "" without NOMAD"""
        return f"{self._url}/maps?lat={lat:.6f}&lng={lon:.6f}&zoom={int(zoom)}" if self._url else ""

    def probe(self) -> None:
        """looks up the library and the maps of the configured url. a part that fails is not there until the next probe"""
        url = normalize_nomad_url(self._url_source())
        kiwix, library, offline_map = "", None, None
        if url:
            kiwix = self._find_kiwix(url)
            library = self._probe_library(kiwix) if kiwix else None
            offline_map = self._probe_map(url)
        with self._lock:
            self._url, self._kiwix_url, self._library, self._map = url, kiwix, library, offline_map
        allow_endpoints([endpoint(u) for u in (url, kiwix) if u])
        state = (url, kiwix if library else "", len(offline_map.archives()) if offline_map else 0)
        if state != self._state:
            self._state = state
            if url:
                logger.info(f"nomad {url}: library {state[1] or '-'}, offline map {state[2]} file(s)")
            else:
                logger.info("nomad: not configured")

    def _json(self, url: str):
        resp = self._get(url, timeout=NOMAD_TIMEOUT)
        if resp.status_code != 200:
            raise IOError(f"{url} answered {resp.status_code}")
        return resp.json()

    def _find_kiwix(self, url: str) -> str:
        """the library's url from NOMAD's services: its custom_url, else NOMAD's host with its port (ui_location "8090"
        or "https:8090"). "" when it is not installed or not running"""
        try:
            services = self._json(f"{url}/api/system/services")
        except Exception as e:
            logger.debug(f"nomad services {url}: {e!r}")
            return ""
        service = next((s for s in services if isinstance(s, dict) and s.get("service_name") == KIWIX_SERVICE), None) \
            if isinstance(services, list) else None
        if not service or not service.get("installed") or service.get("status") not in (None, "running"):
            return ""
        if service.get("custom_url"):
            return normalize_nomad_url(service["custom_url"])
        location = str(service.get("ui_location") or "")
        match = re.fullmatch(r"(?:(https?):)?(\d+)", location)
        if not match:
            return ""
        return f"{match.group(1) or 'http'}://{urlparse(url).hostname}:{match.group(2)}"

    def _probe_library(self, kiwix: str) -> Optional[Library]:
        library = Library(kiwix, self._get)
        return library if library.answers(NOMAD_TIMEOUT) else None

    def _probe_map(self, url: str) -> Optional[OfflineMap]:
        """the regions (detailed) first, the world map last. no world map: no offline map"""
        world = PmtilesArchive(f"{url}/pmtiles/{WORLD_MAP}", self._get)
        try:
            world.header()
        except Exception as e:
            logger.debug(f"offline map {url}: {e!r}")
            return None
        regions = []
        try:
            files = self._json(f"{url}/api/maps/regions").get("files") or []
            names = [f.get("name", "") for f in files if isinstance(f, dict)]
            regions = [PmtilesArchive(f"{url}/pmtiles/{name}", self._get) for name in names
                       if name.endswith(".pmtiles") and name != WORLD_MAP and "/" not in name]
        except Exception as e:
            logger.debug(f"map regions {url}: {e!r}")
        return OfflineMap(regions + [world])
