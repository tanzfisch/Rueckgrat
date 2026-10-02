import asyncio
import flet as ft


class MessageBox(ft.AlertDialog):
    def __init__(self, message="Are you sure?"):
        self._future = None
        super().__init__(
            modal=True,
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(message, text_align=ft.TextAlign.CENTER),
                        ft.Row(
                            [
                                ft.Button("Ok", expand=True, on_click=self._ok),
                                ft.Button("Cancel", expand=True, on_click=self._cancel),
                            ],
                        ),
                    ],
                    tight=True,
                    spacing=15,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                padding=20,
                width=320,
                data={"id": "overlay_dialog"},
            ),
            on_dismiss=self._dismiss,
        )

    def _finish(self, value: bool):
        if self._future and not self._future.done():
            self._future.set_result(value)
        if self.page:
            self.page.close(self)

    def _ok(self, e):
        self._finish(True)

    def _cancel(self, e):
        self._finish(False)

    def _dismiss(self, e):
        self._finish(False)

    @classmethod
    async def open(cls, page: ft.Page, message="Are you sure?") -> bool:
        box = cls(message)
        box._future = asyncio.get_running_loop().create_future()
        page.open(box)
        return await box._future