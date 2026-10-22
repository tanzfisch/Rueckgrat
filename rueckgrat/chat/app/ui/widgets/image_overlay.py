from pathlib import Path
from datetime import datetime
import asyncio
import mimetypes
import flet as ft

from app.common import get_logger
from app.utils import Paths
logger = get_logger()

TOOLS_HIDE_DELAY = 3  # seconds after the last interaction until save and share fade out


class ImageOverlay(ft.Container):
    def __init__(self, page: ft.Page, image_path: Path | str):
        self._future = None
        self._closed = False
        self._hide_task = None
        self._file_picker = None
        self.image_path = Path(image_path)
        # not self.image: that is a Container property (background image)
        self.photo = ft.Image(
            src=Paths.image_src(image_path, page.web),
            fit=ft.BoxFit.CONTAIN,
            width=page.width,
            height=page.height,
        )
        self.viewer = ft.InteractiveViewer(
            min_scale=1,
            max_scale=5,
            content=self.photo,
            on_interaction_start=self._on_interaction,
            on_interaction_update=self._on_interaction,
        )
        # share_plus can't share files on linux, so no share button there
        can_share = page.platform != ft.PagePlatform.LINUX
        self.tools = ft.Container(
            right=16,
            bottom=16,
            opacity=1,
            animate_opacity=300,
            # page.overlay gets no safe area from the view, so keep the buttons 16 px above the android nav bar
            # (and beside it in landscape) ourselves; flutter tracks the insets, no python side events needed
            content=ft.SafeArea(
                avoid_intrusions_left=False,
                avoid_intrusions_top=False,
                content=ft.Row(
                    tight=True,
                    controls=[
                        ft.IconButton(ft.Icons.DOWNLOAD, icon_color=ft.Colors.WHITE, tooltip="save", on_click=self._on_save),
                        ft.IconButton(ft.Icons.SHARE, icon_color=ft.Colors.WHITE, tooltip="share", on_click=self._on_share, visible=can_share),
                    ],
                ),
            ),
        )
        super().__init__(
            left=0,
            top=0,
            width=page.width,
            height=page.height,
            bgcolor=ft.Colors.with_opacity(0.85, ft.Colors.BLACK),
            alignment=ft.Alignment.CENTER,
            on_click=self._close,
            content=ft.Stack([self.viewer, self.tools]),
        )

    def _close(self, e=None):
        self._closed = True
        if self._hide_task:
            self._hide_task.cancel()
        if self.page and self in self.page.overlay:
            self.page.overlay.remove(self)
            self.page.update()
        if self._future and not self._future.done():
            self._future.set_result(None)

    def did_mount(self):
        self._prev_resize = self.page.on_resize
        self.page.on_resize = self._on_resize
        self._show_tools()

    def will_unmount(self):
        self._closed = True
        if self._hide_task:
            self._hide_task.cancel()
        if self.page and self.page.on_resize == self._on_resize:
            self.page.on_resize = self._prev_resize

    def _on_resize(self, e):
        self.width = self.height = None
        self.width = self.page.width
        self.height = self.page.height
        self.photo.width = self.page.width
        self.photo.height = self.page.height
        self.update()
        if self._prev_resize:
            self._prev_resize(e)

    def _update_tools(self):
        """the view can be closed while the hide timer runs, then there is nothing to update"""
        if self._closed:
            return
        try:
            self.tools.update()
        except RuntimeError:
            pass

    def _show_tools(self):
        """shows save and share and (re)starts the hide timer. faded out they are disabled, so taps go through to the view"""
        if self._hide_task:
            self._hide_task.cancel()  # a stale timer must not hide them right after this interaction
        if self.tools.disabled:
            self.tools.opacity = 1
            self.tools.disabled = False
            self._update_tools()
        self._hide_task = self.page.run_task(self._hide_tools_later)

    async def _hide_tools_later(self):
        await asyncio.sleep(TOOLS_HIDE_DELAY)
        self.tools.opacity = 0
        self.tools.disabled = True
        self._update_tools()

    async def _on_interaction(self, e):
        self._show_tools()

    def _file_name(self) -> str:
        # cached images are named by their hash, a timestamp is more useful to the user
        return f"rueckgrat_{datetime.now():%Y%m%d_%H%M%S}{self.image_path.suffix or '.png'}"

    async def _on_save(self, e):
        self._show_tools()
        if self._file_picker is None:
            self._file_picker = ft.FilePicker()
        try:
            # android needs the bytes, on desktop flet writes them to the chosen path
            await self._file_picker.save_file(
                dialog_title="Save image",
                file_name=self._file_name(),
                src_bytes=self.image_path.read_bytes(),
            )
        except Exception as ex:
            logger.error(f"failed saving image {self.image_path}: {repr(ex)}")

    async def _on_share(self, e):
        self._show_tools()
        try:
            # bytes, not the path: on android the python cache path means nothing to the share sheet
            await ft.Share().share_files([
                ft.ShareFile.from_bytes(self.image_path.read_bytes(), mime_type=mimetypes.guess_type(self.image_path.name)[0] or "image/png", name=self._file_name()),
            ])
        except Exception as ex:
            logger.error(f"failed sharing image {self.image_path}: {repr(ex)}")

    @classmethod
    def close_open(cls, page: ft.Page) -> bool:
        """closes the full screen image if one is shown, returns True if it did"""
        for control in reversed(page.overlay):
            if isinstance(control, cls):
                control._close()
                return True
        return False

    @classmethod
    async def open(cls, page: ft.Page, image_path: Path | str):
        overlay = cls(page, image_path)
        overlay._future = asyncio.get_running_loop().create_future()
        page.overlay.append(overlay)
        page.update()
        await overlay._future
