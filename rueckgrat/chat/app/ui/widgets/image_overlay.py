from pathlib import Path
import asyncio
import flet as ft


class ImageOverlay(ft.AlertDialog):
    def __init__(self, image_path: Path | str):
        self._future = None
        super().__init__(
            modal=True,
            bgcolor=ft.Colors.with_opacity(0.85, ft.Colors.BLACK),
            content=ft.GestureDetector(
                content=ft.Image(
                    src=str(image_path),
                    fit=ft.BoxFit.CONTAIN,
                    expand=True,
                ),
                on_tap=self._close,
            ),
            on_dismiss=self._dismiss,
        )

    def _close(self, e=None):
        if self.page:
            self.page.close(self)
        self._finish()

    def _dismiss(self, e):
        self._finish()

    def _finish(self):
        if self._future and not self._future.done():
            self._future.set_result(None)

    @classmethod
    async def open(cls, page: ft.Page, image_path: Path | str):
        overlay = cls(image_path)
        overlay._future = asyncio.get_running_loop().create_future()
        page.open(overlay)
        await overlay._future