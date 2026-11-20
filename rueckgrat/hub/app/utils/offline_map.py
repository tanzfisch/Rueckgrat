"""
Offline map tiles: the hub draws the 256 px png tiles of the map bubble itself from Project NOMAD's Protomaps vector
tiles (.pmtiles files served with byte ranges: <nomad>/pmtiles/<file>). The detailed region extracts first, world.pmtiles
(zoom 0-5) where they have no tile, a zoom beyond a file's max zoom is drawn from its deepest tile (overzoom).
A simple light style: water, land, parks and woods, buildings, roads, borders and place names. Place names are the English
name where the tiles have one, else the local name, drawn in the first of the Noto fonts (hub Dockerfile) that has all its
glyphs: Latin, Cyrillic, Greek, Arabic, Hebrew, Thai, Devanagari, Chinese, Japanese and Korean, right to left and shaped by
Pillow's raqm layout. A name no font can draw is left out rather than drawn as boxes.
"""
import gzip
import io
import math
import threading
import unicodedata
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from app.common import get_logger
logger = get_logger()

TILE_SIZE = 256
SCALE = 2                       # drawn at 2x and scaled down, smooth lines without antialiasing support
MAP_TIMEOUT = 10
DIRECTORY_CACHE = 64            # pmtiles directories kept per file (the root and the leaves used last)

WATER = "#aad3df"
LAND = "#f2efe9"
FILLS = [   # (layer, kinds or None for all, colour) in drawing order
    ("earth", None, LAND),
    ("landcover", ("forest", "wood"), "#cfe3c0"),
    ("landcover", ("grassland", "scrub", "farmland"), "#e3ecd3"),
    ("landcover", ("glacier",), "#ffffff"),
    ("landuse", ("residential", "urban_area"), "#e8e3dc"),
    ("landuse", ("park", "nature_reserve", "national_park", "wood", "forest", "meadow", "grass", "pitch", "garden", "cemetery",
                 "golf_course", "scrub", "protected_area"), "#c8e6b4"),
    ("landuse", ("industrial", "commercial", "retail", "military", "railway"), "#e9dfe6"),
    ("water", None, WATER),
    ("buildings", None, "#d9d0c9"),
]
ROADS = [   # (kinds, colour, width in px at zoom 15, minimum width), drawn from the smallest up
    (("path", "other"), "#ffffff", 1.0, 0.0),
    (("minor_road",), "#ffffff", 3.0, 0.0),
    (("rail",), "#b0aaa8", 1.5, 0.5),
    (("major_road",), "#fff3c4", 5.0, 0.7),
    (("highway",), "#f7c87b", 6.0, 1.0),
]
PLACE_RANK = {"country": 0, "region": 1, "locality": 2, "macrohood": 3, "neighbourhood": 4}
PLACE_MIN_ZOOM = {"country": 0, "region": 5, "locality": 6, "macrohood": 12, "neighbourhood": 14}
MAX_LABELS = 12
LABEL_NAMES = ("name:en", "name")       # the first a place has is its label
FONT_FILES = [  # (file, face index) in order of preference, from fonts-noto-core and fonts-noto-cjk
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", 0),     # Latin, Cyrillic, Greek
    ("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),     # Chinese, Japanese, Korean (the JP face)
]


class PmtilesArchive:
    """one .pmtiles file over http byte ranges. header and directories are cached, a tile is read with one request"""

    def __init__(self, url: str, http_get: Callable = requests.get):
        self._url = url
        self._get = http_get
        self._header: Optional[Dict[str, Any]] = None
        self._directories: "OrderedDict[Tuple[int, int], list]" = OrderedDict()
        self._lock = threading.Lock()

    def url(self) -> str:
        return self._url

    def _bytes(self, offset: int, length: int) -> bytes:
        resp = self._get(self._url, headers={"Range": f"bytes={offset}-{offset + length - 1}"}, timeout=MAP_TIMEOUT)
        if resp.status_code not in (200, 206):
            raise IOError(f"{self._url} answered {resp.status_code}")
        data = resp.content
        return data[offset:offset + length] if resp.status_code == 200 else data    # a server without ranges sends it all

    def header(self) -> Dict[str, Any]:
        """the pmtiles header (zooms, bounds, compression), read once"""
        from pmtiles.tile import deserialize_header
        with self._lock:
            if self._header is None:
                self._header = deserialize_header(self._bytes(0, 127))
            return self._header

    def _directory(self, offset: int, length: int) -> list:
        from pmtiles.tile import deserialize_directory
        key = (offset, length)
        with self._lock:
            if key in self._directories:
                self._directories.move_to_end(key)
                return self._directories[key]
        entries = deserialize_directory(self._bytes(offset, length))
        with self._lock:
            self._directories[key] = entries
            if len(self._directories) > DIRECTORY_CACHE:
                self._directories.popitem(last=False)
        return entries

    def covers(self, z: int, x: int, y: int) -> bool:
        """the tile lies (partly) in the file's bounds and the file starts at or above its zoom"""
        h = self.header()
        if z < h["min_zoom"]:
            return False
        west, north = tile_lonlat(z, x, y)
        east, south = tile_lonlat(z, x + 1, y + 1)
        return not (east < h["min_lon_e7"] / 1e7 or west > h["max_lon_e7"] / 1e7 or
                    north < h["min_lat_e7"] / 1e7 or south > h["max_lat_e7"] / 1e7)

    def max_zoom(self) -> int:
        return self.header()["max_zoom"]

    def tile(self, z: int, x: int, y: int) -> Optional[bytes]:
        """the uncompressed vector tile, None when the file has none there"""
        from pmtiles.tile import zxy_to_tileid, find_tile, Compression
        h = self.header()
        tile_id = zxy_to_tileid(z, x, y)
        offset, length = h["root_offset"], h["root_length"]
        for _ in range(4):      # the spec's max depth
            entry = find_tile(self._directory(offset, length), tile_id)
            if entry is None:
                return None
            if entry.run_length == 0:
                offset, length = h["leaf_directory_offset"] + entry.offset, entry.length
                continue
            data = self._bytes(h["tile_data_offset"] + entry.offset, entry.length)
            return gzip.decompress(data) if h["tile_compression"] == Compression.GZIP else data
        return None


class LabelFonts:
    """the label font for a text: the first of the font files that has all its glyphs. Missing files are left out,
    each file's character map is read once"""

    def __init__(self, files: List[Tuple[str, int]]):
        self._files = files
        self._cmaps: Optional[List[Tuple[str, int, frozenset]]] = None
        self._sized: Dict[Tuple[str, int, int], Any] = {}
        self._lock = threading.Lock()

    def _load(self) -> List[Tuple[str, int, frozenset]]:
        with self._lock:
            if self._cmaps is None:
                from fontTools.ttLib import TTFont, TTLibError
                cmaps = []
                for path, index in self._files:
                    try:
                        with TTFont(path, fontNumber=index, lazy=True) as font:
                            cmaps.append((path, index, frozenset(font.getBestCmap())))
                    except (OSError, TTLibError) as e:      # missing, broken, or no such face in the collection
                        logger.debug(f"label font {path}#{index} left out: {e}")
                if not cmaps:
                    logger.warning("no label fonts installed, offline map tiles have no place names")
                self._cmaps = cmaps
            return self._cmaps

    def font_file(self, text: str) -> Optional[Tuple[str, int]]:
        """(file, face index) of the first font with every glyph of text, None when none has them all"""
        needed = {ord(c) for c in text if not c.isspace() and unicodedata.category(c) != "Cf"}   # Cf: joiners, direction marks
        for path, index, cmap in self._load():
            if needed <= cmap:
                return path, index
        return None

    def font(self, text: str, size: int):
        """the Pillow font to draw text in at size px, None when no font has all its glyphs"""
        found = self.font_file(text)
        if found is None:
            return None
        from PIL import ImageFont
        key = (found[0], found[1], size)
        with self._lock:
            if key not in self._sized:
                self._sized[key] = ImageFont.truetype(found[0], size, index=found[1])
            return self._sized[key]


LABEL_FONTS = LabelFonts(FONT_FILES)


def tile_lonlat(z: int, x: int, y: int) -> Tuple[float, float]:
    """lon, lat of a tile's north west corner"""
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


class OfflineMap:
    """the png tiles from the archives, the regions first, world last (archives in that order)"""

    def __init__(self, archives: List[PmtilesArchive]):
        self._archives = list(archives)

    def archives(self) -> List[PmtilesArchive]:
        return list(self._archives)

    def _source(self, z: int, x: int, y: int) -> Optional[Tuple[Dict[str, Any], int, int, int]]:
        """(decoded vector tile, its zoom, x, y) of the first archive that has the tile or an ancestor at its max zoom"""
        import mapbox_vector_tile
        for archive in self._archives:
            try:
                if not archive.covers(z, x, y):
                    continue
                sz = min(z, archive.max_zoom())
                sx, sy = x >> (z - sz), y >> (z - sz)
                data = archive.tile(sz, sx, sy)
            except Exception as e:
                logger.warning(f"offline map {archive.url()} tile {z}/{x}/{y}: {e!r}")
                continue
            if data:
                return mapbox_vector_tile.decode(data, default_options={"y_coord_down": True}), sz, sx, sy
        return None

    def render(self, z: int, x: int, y: int) -> Optional[bytes]:
        """png bytes of one tile, None when no archive has anything there"""
        source = self._source(z, x, y)
        if source is None:
            return None
        layers, sz, sx, sy = source
        return TileRenderer(layers, z, x, y, sz, sx, sy).png()


class TileRenderer:
    """draws one tile from the layers of its source tile (sz, sx, sy: the same tile, or an ancestor when overzoomed)"""

    def __init__(self, layers: Dict[str, Any], z: int, x: int, y: int, sz: int, sx: int, sy: int):
        from PIL import Image, ImageDraw
        self._layers = layers
        self._z = z
        self._size = TILE_SIZE * SCALE
        self._factor = 2 ** (z - sz)
        self._offset = ((x - (sx << (z - sz))) * self._size, (y - (sy << (z - sz))) * self._size)
        self._image = Image.new("RGB", (self._size, self._size), WATER)
        self._draw = ImageDraw.Draw(self._image)
        self._labels: List[Tuple[float, float, float, float]] = []

    def _point(self, extent: int, point) -> Tuple[float, float]:
        scale = self._size * self._factor / extent
        return point[0] * scale - self._offset[0], point[1] * scale - self._offset[1]

    def _features(self, layer: str, kinds=None):
        data = self._layers.get(layer)
        if not data:
            return
        for feature in data.get("features", []):
            if kinds is None or feature.get("properties", {}).get("kind") in kinds:
                yield data.get("extent", 4096), feature

    def _polygons(self, extent: int, geometry) -> list:
        kind, coords = geometry.get("type"), geometry.get("coordinates") or []
        polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
        return [[[self._point(extent, p) for p in ring] for ring in polygon] for polygon in polygons]

    def _lines(self, extent: int, geometry) -> list:
        kind, coords = geometry.get("type"), geometry.get("coordinates") or []
        lines = [coords] if kind == "LineString" else coords if kind == "MultiLineString" else []
        return [[self._point(extent, p) for p in line] for line in lines]

    def _fill(self, layer: str, kinds, colour: str) -> None:
        from PIL import Image, ImageDraw
        mask = Image.new("L", (self._size, self._size), 0)
        draw = ImageDraw.Draw(mask)
        drawn = False
        for extent, feature in self._features(layer, kinds):
            for polygon in self._polygons(extent, feature["geometry"]):
                for i, ring in enumerate(polygon):
                    if len(ring) >= 3:
                        draw.polygon(ring, fill=0 if i else 255)     # the first ring is the outline, the others holes
                        drawn = True
        if drawn:
            self._image.paste(colour, (0, 0), mask)

    def _width(self, width: float, minimum: float) -> int:
        return max(1, round(max(minimum, width * 2 ** ((self._z - 15) / 1.5)) * SCALE))

    def _roads(self) -> None:
        for kinds, colour, width, minimum in ROADS:
            if minimum == 0.0 and self._z < 12:
                continue    # small roads only close up
            w = self._width(width, minimum)
            for extent, feature in self._features("roads", kinds):
                for line in self._lines(extent, feature["geometry"]):
                    if len(line) >= 2:
                        self._draw.line(line, fill=colour, width=w, joint="curve")

    def _borders(self) -> None:
        for extent, feature in self._features("boundaries"):
            colour = "#8f8aa3" if feature.get("properties", {}).get("kind") == "country" else "#b9b4c7"
            for line in self._lines(extent, feature["geometry"]):
                if len(line) >= 2:
                    self._draw.line(line, fill=colour, width=SCALE)

    def _places(self) -> None:
        places = []
        for extent, feature in self._features("places"):
            props = feature.get("properties", {})
            kind, name = props.get("kind"), next((props[key] for key in LABEL_NAMES if props.get(key)), None)
            if not name or kind not in PLACE_RANK or self._z < PLACE_MIN_ZOOM[kind]:
                continue
            if feature["geometry"].get("type") != "Point":
                continue
            places.append((PLACE_RANK[kind], props.get("population_rank", 0) * -1, name, self._point(extent, feature["geometry"]["coordinates"])))
        for rank, _, name, (px, py) in sorted(places)[:MAX_LABELS * 3]:
            if len(self._labels) >= MAX_LABELS:
                break
            font = LABEL_FONTS.font(name, (14 if rank <= 1 else 12) * SCALE)
            if font is None:
                continue
            box = self._draw.textbbox((px, py), name, font=font, anchor="mm")
            if box[2] < 0 or box[0] > self._size or box[3] < 0 or box[1] > self._size:
                continue
            if any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in self._labels):
                continue
            self._labels.append(box)
            self._draw.text((px, py), name, fill="#333333", font=font, anchor="mm", stroke_width=2 * SCALE, stroke_fill="#ffffff")

    def png(self) -> bytes:
        from PIL import Image
        if "earth" not in self._layers:
            self._image.paste(LAND, (0, 0, self._size, self._size))     # a tile without earth polygons inland: all land
        for layer, kinds, colour in FILLS:
            self._fill(layer, kinds, colour)
        self._roads()
        self._borders()
        self._places()
        out = io.BytesIO()
        self._image.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS).save(out, format="PNG", optimize=True)
        return out.getvalue()
