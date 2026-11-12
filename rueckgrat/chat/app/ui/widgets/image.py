import os
import asyncio
import struct
from pathlib import Path
import flet as ft

from .image_overlay import ImageOverlay

from app.common import get_logger
from app.utils import Paths
logger = get_logger()

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"


class Image(ft.GestureDetector):
    def __init__(self, image_path: Path, size: tuple[int, int] | None = None, fit: ft.BoxFit = ft.BoxFit.CONTAIN, fill: bool = False, max_edge: int | None = None, **kwargs):
        self.image_path = Path(image_path) if image_path else Path()
        self.fixed_size = size
        self.max_edge = max_edge     # the longer side is at most this, sized once the file exists
        self._poll_task = None

        w, h = size if size else (None, None)

        self.loading = ft.Image(
            src=f"{ASSETS_DIR}/icons/loading.gif",
            width=32,
            height=32,
            fit=ft.BoxFit.CONTAIN,
        )
        self.photo = ft.Image(
            src=None,
            width=w,
            height=h,
            fit=fit,
            visible=False,
        )
        if fill or max_edge:    # the photo takes the size the parent gives, e.g. a grid tile
            self.photo.left = self.photo.top = self.photo.right = self.photo.bottom = 0
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
        if not self.image_path:
            return
        
        while True:
            if self.image_path.exists():
                self.photo.src = Paths.image_src(self.image_path, self.page.web)
                self.photo.visible = True
                self.loading.visible = False
                if self.max_edge:
                    self._fit_max_edge()
                self.update()
                return
            await asyncio.sleep(0.5)

    def _fit_max_edge(self):
        """scales down to max_edge on the longer side keeping the aspect ratio, never up. narrower parents shrink it further"""
        size = self._pixel_size()
        if not size:
            self.width = self.height = self.max_edge   # unknown format: a square box, the photo is contained in it
            return
        w, h = size
        self.width = round(w * min(1.0, self.max_edge / max(w, h)))
        self.stack.aspect_ratio = w / h

    def _pixel_size(self) -> tuple[int, int] | None:
        """width and height from the file header (png, jpeg, gif, webp), None if unknown"""
        try:
            with open(self.image_path, "rb") as f:
                head = f.read(32)
                if head.startswith(b"\x89PNG"):
                    return struct.unpack(">II", head[16:24])
                if head[:6] in (b"GIF87a", b"GIF89a"):
                    return struct.unpack("<HH", head[6:10])
                if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                    chunk = head[12:16]
                    if chunk == b"VP8 ":
                        w, h = struct.unpack("<HH", head[26:30])
                        return w & 0x3FFF, h & 0x3FFF
                    if chunk == b"VP8L":
                        b = head[21:25]
                        return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                    if chunk == b"VP8X":
                        return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
                    return None
                if head[:2] == b"\xff\xd8":
                    f.seek(2)
                    while True:
                        marker = f.read(2)
                        if len(marker) < 2 or marker[0] != 0xFF:
                            return None
                        length = struct.unpack(">H", f.read(2))[0]
                        if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                            h, w = struct.unpack(">xHH", f.read(5))
                            return w, h
                        f.seek(length - 2, 1)
        except (OSError, struct.error):
            pass
        return None

    async def _open(self, e):
        if self.image_path.exists():
            await ImageOverlay.open(self.page, self.image_path)