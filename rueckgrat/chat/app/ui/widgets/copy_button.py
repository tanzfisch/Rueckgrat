"""the copy button of the chat's text blocks (code, quote, table, text), of a whole reply and of the text preview: a click
puts its text into the clipboard, the icon shows a check for a moment. The compact one of the text blocks is no higher than
a line of text, so it overlays a block's top right corner without making a one line block taller"""
import asyncio
from typing import Callable
import flet as ft
from app.ui import theme


class CopyButton(ft.IconButton):
    clipboard = ft.Clipboard    # the clipboard service, made on each copy (a fake in tests)
    CHECK_SECONDS = 1.5         # how long the check shows after a copy
    COMPACT = 18                # px of the compact button at text size 1.0, a body text line is ~20
    COMPACT_ICON = 14

    def __init__(self, text: str | Callable[[], str], tooltip: str = "Copy", compact: bool = False, **kwargs):
        """text: the copied text, or a function giving it at the click (a reply that still grows).
        compact: the small button of the text blocks, no padding, compact_size() square"""
        if compact:
            size = self.compact_size()
            kwargs.update(padding=0, visual_density=ft.VisualDensity.COMPACT,
                          size_constraints=ft.BoxConstraints(min_width=size, max_width=size, min_height=size, max_height=size))
        super().__init__(icon=ft.Icons.CONTENT_COPY, icon_size=round(self.COMPACT_ICON * theme.SIZE_FACTOR) if compact else 16,
                         icon_color=theme.TEXT, tooltip=tooltip, on_click=self._on_click, **kwargs)
        self._text = text
        self._mounted = False

    @classmethod
    def compact_size(cls) -> int:
        """px of the compact button with the active text size"""
        return round(cls.COMPACT * theme.SIZE_FACTOR)

    def did_mount(self):
        hook = getattr(super(), "did_mount", None)
        if callable(hook):
            hook()
        self._mounted = True

    def will_unmount(self):
        self._mounted = False
        hook = getattr(super(), "will_unmount", None)
        if callable(hook):
            hook()

    def text(self) -> str:
        """what a click copies"""
        return self._text() if callable(self._text) else self._text

    async def copy(self) -> None:
        await self.clipboard().set(self.text())

    async def _on_click(self, e):
        await self.copy()
        self._show(ft.Icons.CHECK)
        await asyncio.sleep(self.CHECK_SECONDS)
        self._show(ft.Icons.CONTENT_COPY)

    def _show(self, icon) -> None:
        """sets the icon; update() only while the button is on the page (a streamed block may have been re-rendered)"""
        self.icon = icon
        if self._mounted:
            self.update()
