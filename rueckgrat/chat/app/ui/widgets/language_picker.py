import asyncio
import flet as ft

from app.common.languages import LANGUAGES


def flag_text(code: str, size: int = 22) -> ft.Text:
    """the flag emoji of a language, in the color emoji font like the EmojiPicker"""
    return ft.Text(LANGUAGES[code]["flag"], size=size, font_family="Noto Color Emoji")


class LanguagePicker:
    """dialog with the translator languages, open() returns the picked code or "" """

    def __init__(self, page: ft.Page, current: str):
        self.page = page
        self._future = None
        tiles = [
            ft.ListTile(
                leading=flag_text(code),
                title=ft.Text(language["name"]),
                selected=code == current,
                on_click=lambda e, c=code: self._pick(c),
            )
            for code, language in LANGUAGES.items()
        ]
        self.dialog = ft.AlertDialog(
            open=True,
            modal=False,
            content=ft.Container(width=280, height=420, content=ft.ListView(controls=tiles)),
            on_dismiss=self._dismiss,
        )

    def _pick(self, code: str):
        if self._future and not self._future.done():
            self._future.set_result(code)
        self.page.pop_dialog()

    def _dismiss(self, e):
        if self._future and not self._future.done():
            self._future.set_result("")

    @classmethod
    async def open(cls, page: ft.Page, current: str) -> str:
        picker = cls(page, current)
        picker._future = asyncio.get_running_loop().create_future()
        page.show_dialog(picker.dialog)
        page.update()
        return await picker._future
