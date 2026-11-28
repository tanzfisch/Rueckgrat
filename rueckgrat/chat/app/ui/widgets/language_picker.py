import asyncio
import flet as ft

from app.common.languages import LANGUAGES


def flag_text(code: str, size: int = 22) -> ft.Control:
    """the flag emoji of a language, in the color emoji font like the EmojiPicker"""
    return ft.Text(LANGUAGES[code]["flag"], size=size, font_family="Noto Color Emoji")


class LanguagePicker:
    """dialog with the translator languages (sorted by name, the native name below), open() returns the picked code or "" (dismissed).
    auto: a first entry, the globe "Auto-detect" (whisper detects the language), picking it returns AUTO, current "" selects it"""
    AUTO = "auto"

    def __init__(self, page: ft.Page, current: str, auto: bool = False):
        self.page = page
        self._future = None
        tiles = [ft.ListTile(
            leading=ft.Icon(ft.Icons.LANGUAGE),
            title=ft.Text("Auto-detect"),
            selected=not current,
            on_click=lambda e: self._pick(self.AUTO),
        )] if auto else []
        tiles += [
            ft.ListTile(
                leading=flag_text(code),
                title=ft.Text(language["name"]),
                subtitle=ft.Text(language["native_name"]) if language["native_name"] != language["name"] else None,
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
    async def open(cls, page: ft.Page, current: str, auto: bool = False) -> str:
        picker = cls(page, current, auto)
        picker._future = asyncio.get_running_loop().create_future()
        page.show_dialog(picker.dialog)
        page.update()
        return await picker._future
