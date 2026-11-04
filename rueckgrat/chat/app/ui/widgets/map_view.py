import math
from urllib.parse import quote
import flet as ft
from app.ui import theme
from app.utils import Hub

from app.common import get_logger
logger = get_logger()

TILE_SIZE = 256
MAP_HEIGHT = 180
PIN_SIZE = 36
ATTRIBUTION = "© OpenStreetMap contributors"
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
# dark mode: the light osm tiles inverted (and dimmed a bit), close to a dark map style without a second tile source
DARK_FILTER = {"color": ft.Colors.WHITE, "color_blend_mode": ft.BlendMode.DIFFERENCE}
MAX_CACHED_TILES = 64
_tiles: dict[tuple, bytes] = {}     # (z, x, y) -> png, the tiles of the maps shown in this session


def _world_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """web mercator pixel of a point in the whole world map at zoom"""
    size = TILE_SIZE * 2 ** zoom
    lat = math.radians(max(-85.0511, min(85.0511, lat)))
    return (lon + 180) / 360 * size, (1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * size


def map_url(place: dict, android: bool) -> str:
    """android: a geo: uri, the maps app pins the coordinates with the label.
    else google maps search: the address text finds the place with its place card, the coordinates if there is no text"""
    lat, lon = place["lat"], place["lon"]
    if android:
        label = place.get("label") or place.get("query") or place.get("display_name") or ""
        return f"geo:{lat},{lon}?q={lat},{lon}" + (f"({quote(label)})" if label else "")
    return f"https://www.google.com/maps/search/?api=1&query={quote(place.get('query') or f'{lat},{lon}')}"


class MapView(ft.Column):
    """the map bubble under an assistant answer: osm tiles (through the hub) around the place with a pin, the label under it.
    a tap anywhere opens the place in the maps app (android) or google maps"""
    def __init__(self, place: dict):
        super().__init__(spacing=6, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.place = place
        self.zoom = int(place.get("zoom") or 15)
        self.center = _world_pixel(float(place["lat"]), float(place["lon"]), self.zoom)
        self.width_px = 320     # until the first size event
        self.images: dict[tuple, ft.Image] = {}     # (z, x, y) -> the image of a loaded tile
        self.tile_layer = ft.Stack(expand=True)
        self.pin = ft.Icon(ft.Icons.LOCATION_ON, size=PIN_SIZE, color=ft.Colors.RED_600)
        self.map = ft.Stack(
            height=MAP_HEIGHT,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            size_change_interval=200,
            on_size_change=self._on_size,
            controls=[
                self.tile_layer,
                ft.Container(expand=True, bgcolor=ft.Colors.with_opacity(0.3, theme.SURFACE), visible=theme.is_dark()),   # softens the inverted tiles
                self.pin,
                ft.Container(
                    right=0, bottom=0, padding=ft.Padding(6, 2, 6, 2),
                    bgcolor=ft.Colors.with_opacity(0.7, theme.SURFACE),
                    border_radius=ft.BorderRadius(theme.RADIUS // 2, 0, 0, 0),
                    on_click=self._on_attribution,
                    content=ft.Text(ATTRIBUTION, size=10, color=theme.TEXT),
                ),
            ],
        )
        title = place.get("label") or place.get("display_name") or place.get("query") or ""
        self.controls = [
            ft.Container(content=self.map, border_radius=theme.RADIUS // 2, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                         bgcolor=theme.SURFACE, on_click=self._on_click),
            ft.Text(title, color=theme.TEXT, weight=ft.FontWeight.BOLD, font_family=theme.TEXT_FONT,
                    font_family_fallback=theme.EMOJI_FALLBACK, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ]
        self._layout()

    def did_mount(self):
        self.page.run_thread(self._load_tiles)

    def _needed(self) -> list[tuple]:
        """the tiles the view shows, (tile x, tile y) at self.zoom, x may lie past the date line"""
        cx, cy = self.center
        x0, x1 = int((cx - self.width_px / 2) // TILE_SIZE), int((cx + self.width_px / 2) // TILE_SIZE)
        y0, y1 = int((cy - MAP_HEIGHT / 2) // TILE_SIZE), int((cy + MAP_HEIGHT / 2) // TILE_SIZE)
        return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1) if 0 <= y < 2 ** self.zoom]

    def _layout(self):
        """tiles placed so the place is in the middle, the pin's tip on it"""
        cx, cy = self.center
        controls = []
        for x, y in self._needed():
            key = (self.zoom, x % 2 ** self.zoom, y)
            image = self.images.get(key)
            if image is None:
                if key not in _tiles:
                    continue    # not loaded yet, the background shows
                image = ft.Image(src=_tiles[key], width=TILE_SIZE, height=TILE_SIZE, gapless_playback=True,
                                 error_content=ft.Container(), **(DARK_FILTER if theme.is_dark() else {}))
                self.images[key] = image
            image.left = x * TILE_SIZE - cx + self.width_px / 2
            image.top = y * TILE_SIZE - cy + MAP_HEIGHT / 2
            controls.append(image)
        self.tile_layer.controls = controls
        self.pin.left = self.width_px / 2 - PIN_SIZE / 2
        self.pin.top = MAP_HEIGHT / 2 - PIN_SIZE

    def _load_tiles(self):
        """the missing tiles from the hub, each shown as it arrives"""
        for x, y in self._needed():
            key = (self.zoom, x % 2 ** self.zoom, y)
            if key in self.images:
                continue
            if key not in _tiles:
                tile = Hub.get_map_tile(*key)
                if not tile:
                    continue
                _tiles[key] = tile
                if len(_tiles) > MAX_CACHED_TILES:
                    del _tiles[next(iter(_tiles))]
            self._layout()
            try:
                self.map.update()
            except Exception:
                return  # the chat was left meanwhile

    def _on_size(self, e: ft.LayoutSizeChangeEvent):
        if not e.width or abs(e.width - self.width_px) < 1:
            return
        self.width_px = e.width
        self._layout()
        self.map.update()
        self.page.run_thread(self._load_tiles)

    async def _on_click(self, e):
        android = self.page.platform == ft.PagePlatform.ANDROID and not self.page.web
        await self._launch(map_url(self.place, android))

    async def _on_attribution(self, e):
        await self._launch(COPYRIGHT_URL)

    async def _launch(self, url: str):
        try:
            await ft.UrlLauncher().launch_url(url)
        except Exception as ex:
            logger.error(f"opening {url} failed: {ex}")
