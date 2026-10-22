from pathlib import Path
import asyncio
import flet as ft

from app.utils import Paths


class ImageOverlay(ft.Container):
    def __init__(self, page: ft.Page, image_path: Path | str):
        self._future = None
        super().__init__(
            left=0,
            top=0,
            width=page.width,
            height=page.height,
            bgcolor=ft.Colors.with_opacity(0.85, ft.Colors.BLACK),
            alignment=ft.Alignment.CENTER,
            on_click=self._close,
            content=ft.InteractiveViewer(
                min_scale=1,
                max_scale=5,
                content=ft.Image(
                    src=Paths.image_src(image_path, page.web),
                    fit=ft.BoxFit.CONTAIN,
                    width=page.width,
                    height=page.height,
                ),
            ),
        )

    def _close(self, e=None):
        if self.page and self in self.page.overlay:
            self.page.overlay.remove(self)
            self.page.update()
        if self._future and not self._future.done():
            self._future.set_result(None)

    def did_mount(self):
        self._prev_resize = self.page.on_resize
        self.page.on_resize = self._on_resize

    def will_unmount(self):
        if self.page and self.page.on_resize == self._on_resize:
            self.page.on_resize = self._prev_resize

    def _on_resize(self, e):
        self.width = self.height = None
        self.width = self.page.width
        self.height = self.page.height
        self.content.content.width = self.page.width
        self.content.content.height = self.page.height
        self.update()
        if self._prev_resize:
            self._prev_resize(e)

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