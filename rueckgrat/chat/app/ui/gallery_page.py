import asyncio
import flet as ft
from app.ui.theme import TEXT_DIM

from app.ui import BasePage
from app.ui.widgets import Header, Image
from app.utils import Hub, Paths
from app.common import get_logger

logger = get_logger()

PAGE_SIZE = 36          # images per hub request, the next page loads when the grid is scrolled near its end
THUMB_SIZE = 160        # max tile width, the grid fits as many columns as the width allows
LOAD_MORE_PX = 600      # scroll distance to the end at which the next page is asked for
IMAGE_TIMEOUT = 120     # seconds a tile waits for its download (mobile data, a queue of downloads), then a warning


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


async def broken_image_fallback(slot: ft.Container, image_path, is_active=lambda: True):
    """the Image widget waits for its file forever: if the download failed (token ran out, hub down, an upload
    the hub lost and can't generate again) warn instead"""
    await asyncio.sleep(IMAGE_TIMEOUT)
    if is_active() and not image_path.exists():
        slot.content = ft.Icon(ft.Icons.BROKEN_IMAGE, color=ft.Colors.ERROR, tooltip="image could not be loaded")
        _update(slot)


class GalleryPage(BasePage):
    """all images of the user across all contacts (and the image tool), newest first, as a grid.
    the hub pages them (GET /gallery), each tile downloads its image into the image cache through the download queue
    and is the chat's Image widget: a tap opens it full screen with save and share.
    with on_select it is a picker (e.g. in a dialog): no header, a tap calls on_select(file_key) instead"""

    def __init__(self, navigator, on_select=None):
        super().__init__(navigator)
        self.on_select = on_select
        self.header = None if on_select else Header(navigator, selected_contact=False)
        if self.header:
            self.header.on_go_back = self.on_go_back
        self._active = False
        self._loading_page = False
        self._next_offset: int | None = 0
        self._shown: set[str] = set()
        self.status = ft.Text("loading...", color=TEXT_DIM)
        self.grid = ft.GridView(
            expand=True,
            max_extent=THUMB_SIZE,
            child_aspect_ratio=0.8,     # room for the label under the image
            spacing=8,
            run_spacing=8,
            on_scroll=self._on_scroll,
            scroll_interval=200,
        )
        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(expand=True, controls=[c for c in (self.header, self.status, self.grid) if c]),
            ),
        ]

    def on_go_back(self, e=None):
        self.navigator("contacts")

    def on_enter(self, **kwargs):
        self._active = True
        self.page.run_task(self._load_page)

    def on_leave(self):
        self._active = False

    def _on_scroll(self, e: ft.OnScrollEvent):
        if e.max_scroll_extent - e.pixels < LOAD_MORE_PX:
            self.page.run_task(self._load_page)

    async def _load_page(self):
        if self._loading_page or self._next_offset is None:
            return
        self._loading_page = True
        try:
            tiles = []
            # the hub leaves out images it can't serve, so a page may come back short or empty: ask on until there is something
            while not tiles and self._next_offset is not None:
                result = await asyncio.to_thread(Hub.get_gallery, self._next_offset, PAGE_SIZE)
                if not self._active:
                    return
                if result is None:
                    self.status.value = "⚠ could not load the images"
                    self.status.color = ft.Colors.ERROR
                    self.status.visible = True
                    _update(self.status)
                    return  # _next_offset stays, the next scroll tries again
                self._next_offset = result.get("next_offset")
                tiles = [self._tile(item) for item in result.get("images", []) if item.get("file_key") and item["file_key"] not in self._shown]
            self.grid.controls += tiles
            self.status.visible = not self.grid.controls
            self.status.value = "no images yet"
            self.status.color = TEXT_DIM
            _update(self.status)
            _update(self.grid)
        except Exception as e:
            logger.error(f"failed to show the gallery {repr(e)}")
        finally:
            self._loading_page = False

    def _tile(self, item: dict) -> ft.Control:
        filename = item["file_key"]
        self._shown.add(filename)
        image_path = Paths.get_image_path() / filename
        if not image_path.exists():
            Hub.download_file(f"images/{filename}", Paths.get_image_path())
        slot = ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            border_radius=8,
            content=Image(image_path, size=(THUMB_SIZE, THUMB_SIZE), fit=ft.BoxFit.COVER),
        )
        if self.on_select:
            slot.content.on_tap = lambda e: self.on_select(filename)
        self.page.run_task(broken_image_fallback, slot, image_path, lambda: self._active)
        label = f"{item.get('contact_name') or 'image tool'} · {str(item.get('created_at') or '')[:10]}"
        return ft.Column(
            spacing=2,
            controls=[slot, ft.Text(label, size=11, color=TEXT_DIM, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)],
        )
