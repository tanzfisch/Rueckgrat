"""a text file shown over the page to scroll through, with syntax colours by its extension. the bytes are fetched on
each open and only kept by the overlay, nothing goes into the database or the cache"""
import asyncio
import posixpath
import re
import flet as ft
from app.ui import theme
from .message_box import MessageBox

from app.common import get_logger
logger = get_logger()

MAX_SIZE = 1024 * 1024      # bigger files are only shown after the user agreed
# file extension: highlight.js language of the code block
LANGUAGES = {
    "py": "python", "js": "javascript", "ts": "typescript", "json": "json", "md": "markdown", "sh": "bash",
    "bash": "bash", "c": "c", "h": "cpp", "cpp": "cpp", "hpp": "cpp", "cc": "cpp", "java": "java", "kt": "kotlin",
    "rs": "rust", "go": "go", "html": "xml", "xml": "xml", "css": "css", "yaml": "yaml", "yml": "yaml",
    "toml": "ini", "ini": "ini", "cfg": "ini", "sql": "sql", "php": "php", "rb": "ruby", "lua": "lua",
    "cs": "csharp", "swift": "swift", "dart": "dart", "dockerfile": "dockerfile", "makefile": "makefile",
}


def language(name: str) -> str:
    """the highlight.js language of a file name, "" when unknown (plain text)"""
    base = posixpath.basename(name).lower()
    return LANGUAGES.get(base.rsplit(".", 1)[-1] if "." in base else base, "")


def decode(data: bytes) -> str | None:
    """the text of a file, None when it is binary"""
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class TextPreview(ft.Container):
    def __init__(self, name: str, text: str):
        # a fence longer than any backtick run in the text, so the text can not end the code block
        fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
        body = ft.Markdown(
            value=f"{fence}{language(name)}\n{text}\n{fence}",
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=theme.CODE_THEME,
        )
        card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, color=theme.TEXT, size=18),
                    ft.Text(name, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=14, expand=True,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.IconButton(icon=ft.Icons.CLOSE, icon_size=20, icon_color=theme.TEXT, tooltip="Close",
                                  on_click=self._close),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                # long lines scroll sideways, the file scrolls down
                ft.Column([ft.Row([body], scroll=ft.ScrollMode.AUTO, wrap=False)], scroll=ft.ScrollMode.AUTO, expand=True),
            ], spacing=4, expand=True),
            bgcolor=theme.BACKGROUND, border_radius=theme.RADIUS, border=ft.Border.all(1, theme.CODE_BORDER),
            padding=ft.Padding(left=12, top=4, right=4, bottom=12),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            on_click=lambda e: None,    # a tap on the file does not close it, only one beside it
        )
        # page.overlay gets no safe area from the view (see ImageOverlay)
        super().__init__(left=0, top=0, right=0, bottom=0, bgcolor=theme.SCRIM, on_click=self._close,
                         padding=16, content=ft.SafeArea(content=card))

    def _close(self, e=None):
        if self.page and self in self.page.overlay:
            page = self.page
            page.overlay.remove(self)
            page.update()

    @classmethod
    def close_open(cls, page: ft.Page) -> bool:
        """closes the preview if one is shown, returns True if it did"""
        for control in reversed(page.overlay):
            if isinstance(control, cls):
                control._close()
                return True
        return False

    @classmethod
    async def open(cls, page: ft.Page, name: str, size: int, fetch) -> None:
        """fetch(): the file's bytes or None, run in a thread. a file over MAX_SIZE asks first"""
        if size > MAX_SIZE and not await MessageBox.open(
                page, f"{posixpath.basename(name)} is {size / 1024 / 1024:.1f} MB. Showing it can take a while. Show it anyway?",
                "Big file", "question"):
            return
        data = await asyncio.to_thread(fetch)
        if data is None:
            MessageBox.error(page, f"{posixpath.basename(name)} could not be fetched.")
            return
        text = decode(data)
        if text is None:
            MessageBox.show(page, f"{posixpath.basename(name)} is not a text file.", "No preview", "info")
            return
        page.overlay.append(cls(name, text))
        page.update()
