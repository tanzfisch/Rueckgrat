from pathlib import Path
from datetime import datetime
import asyncio
import mimetypes
import os
import posixpath
import tempfile
import flet as ft

from app.ui import theme
from .message_box import MessageBox

from app.common import get_logger
from app.utils import Paths
logger = get_logger()

TOOLS_HIDE_DELAY = 3  # seconds after the last interaction until save and share fade out
MAX_SIZE = 20 * 1024 * 1024  # bigger fetched images are only shown after the user agreed
# formats this overlay can show (ft.Image). not svg: the viewer is a raster image
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def is_image(name: str) -> bool:
    """an image file by its name, the overlay can show it"""
    return posixpath.splitext(name.lower())[1] in IMAGE_EXTENSIONS


class ImageOverlay(ft.Container):
    def __init__(self, page: ft.Page, image_path: Path | str, temporary: bool = False):
        self._future = None
        self._closed = False
        self._hide_task = None
        self._file_picker = None
        self._temporary = temporary    # a fetched file written only for this overlay, removed when it closes
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
                        ft.IconButton(ft.Icons.DOWNLOAD, icon_color=theme.ON_SCRIM, tooltip="save", on_click=self._on_save),
                        ft.IconButton(ft.Icons.SHARE, icon_color=theme.ON_SCRIM, tooltip="share", on_click=self._on_share, visible=can_share),
                    ],
                ),
            ),
        )
        super().__init__(
            left=0,
            top=0,
            width=page.width,
            height=page.height,
            bgcolor=theme.SCRIM,
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
        if self._temporary:
            try:
                self.image_path.unlink(missing_ok=True)
            except OSError as ex:
                logger.error(f"failed removing the temporary image {self.image_path}: {repr(ex)}")
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
    async def open(cls, page: ft.Page, image_path: Path | str, temporary: bool = False):
        overlay = cls(page, image_path, temporary=temporary)
        overlay._future = asyncio.get_running_loop().create_future()
        page.overlay.append(overlay)
        page.update()
        await overlay._future

    @classmethod
    async def open_fetched(cls, page: ft.Page, name: str, size: int, fetch) -> None:
        """fetch(): the image bytes or None, run in a thread. shown in the same overlay as a generated image.
        a file over MAX_SIZE asks first. the bytes go to a temp file that is removed when the overlay closes."""
        if size > MAX_SIZE and not await MessageBox.open(
                page, f"{posixpath.basename(name)} is {size / 1024 / 1024:.1f} MB. Loading it can take a while. Show it anyway?",
                "Big file", "question"):
            return
        data = await asyncio.to_thread(fetch)
        if data is None:
            MessageBox.error(page, f"{posixpath.basename(name)} could not be fetched.")
            return
        suffix = posixpath.splitext(name.lower())[1]
        if suffix not in IMAGE_EXTENSIONS:
            suffix = ".png"
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="rueckgrat_")
        os.close(fd)
        try:
            Path(path).write_bytes(data)
        except OSError as ex:
            logger.error(f"failed writing the temporary image {path}: {repr(ex)}")
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
            MessageBox.error(page, f"{posixpath.basename(name)} could not be shown.")
            return
        cls.close_open(page)
        await cls.open(page, path, temporary=True)
