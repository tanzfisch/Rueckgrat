import os
import asyncio
from pathlib import Path
import flet as ft

from .image_overlay import ImageOverlay

from app.common import get_logger
logger = get_logger()

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"


class Image(ft.GestureDetector):
    def __init__(self, image_path: Path, size: tuple[int, int] | None = None, **kwargs):
        self.image_path = Path(image_path) if image_path else Path()
        self.fixed_size = size
        self._poll_task = None

        w, h = size if size else (None, None)

        self.loading = ft.Image(
            src=f"{ASSETS_DIR}/icons/loading.gif",
            width=w or 48,
            height=h or 48,
            fit=ft.BoxFit.CONTAIN,
        )
        self.photo = ft.Image(
            src=None,
            width=w,
            height=h,
            fit=ft.BoxFit.CONTAIN,
            visible=False,
        )
        self.stack = ft.Stack(
            [self.loading, self.photo],
            width=w,
            height=h,
            alignment=ft.Alignment.CENTER,
        )

        super().__init__(content=self.stack, on_tap=self._open, **kwargs)

    def did_mount(self):
        self._poll_task = self.page.run_task(self._poll)

    def will_unmount(self):
        if self._poll_task:
            self._poll_task.cancel()

    async def _poll(self):
        while True:
            if self.image_path and self.image_path.exists():
                self.photo.src = str(self.image_path)
                self.photo.visible = True
                self.loading.visible = False
                self.update()
                return
            await asyncio.sleep(2)

    async def _open(self, e):
        if self.image_path.exists():
            await ImageOverlay.open(self.page, self.image_path)