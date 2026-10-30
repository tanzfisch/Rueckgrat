import re
import flet as ft
from urllib.parse import urlparse
from app.ui.theme import STYLES, MARKDOWN_STYLE
from app.ui.widgets.image import Image

from app.common import get_logger
logger = get_logger()


async def _open_link(e):
    url = e.data
    if url:
        await ft.UrlLauncher().launch_url(url)


FAVICON_SIZE = 20   # source buttons: the favicon and its fallback icon


class BubbleActions(ft.Row):
    """the row of small buttons under a bubble, e.g. play and the sources of a web search"""
    def __init__(self):
        super().__init__(spacing=4, wrap=True, visible=False, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def add_button(self, button: ft.Control) -> ft.Control:
        self.controls.append(button)
        self.visible = True
        return button

    def set_sources(self, sources: list[dict]):
        """a link button per page the answer's web search used, with the site's favicon (a globe if it has none)"""
        self.controls = [c for c in self.controls if c.data != "source"]
        for source in sources:
            url = source.get("url")
            if not url:
                continue

            async def open_url(e, url=url):
                await ft.UrlLauncher().launch_url(url)

            parsed = urlparse(url)
            self.add_button(ft.IconButton(
                icon=ft.Image(
                    src=f"{parsed.scheme}://{parsed.netloc}/favicon.ico",
                    width=FAVICON_SIZE, height=FAVICON_SIZE,
                    error_content=ft.Icon(ft.Icons.PUBLIC, size=FAVICON_SIZE),
                ),
                tooltip=source.get("title") or url,
                data="source",
                on_click=open_url,
            ))


class ChatBubble(ft.Container):
    def __init__(self, role: str, content: str, image_filepath: str | None = None, **kwargs):
        self.body = ft.Column(spacing=8, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        super().__init__(
            content=self.body,
            **kwargs,
        )
        self.role = role
        self.image_filepath = image_filepath
        self.action_row = BubbleActions()   # shown under the bubble by the chat page
        self.raw_content = ""
        self.append_content(content)

    def _clear(self):
        self.body.controls.clear()

    def clear_content(self):
        self.raw_content = ""

    def append_content(self, content: str):
        try:
            self.raw_content += content
            self._clear()

            parsable = self.raw_content
            if parsable.count("```") % 2 == 1:
                parsable += "\n```"

            items = self._parse_content(parsable)

            if self.image_filepath:
                self._add_image(self.image_filepath)

            for item in items:
                if item["type"] == "text":
                    self._add_text(item["value"])
                elif item["type"] == "code":
                    self._add_code(item["value"])
        except Exception as e:
            logger.error(f"failed to append content: {repr(e)}")

    def set_image(self, image_filepath: str):
        """adds the image (placeholder until the file exists) to a bubble that is already shown"""
        if self.image_filepath == image_filepath:
            return
        self.image_filepath = image_filepath
        self.append_content("")     # rebuilds the controls, with the image first
        if self.page:
            self.update()

    def set_fixed_width(self, width: int):
        self.width = width
        if self.page:
            self.update()

    def _md(self, value: str, code: bool = False) -> ft.Markdown:
        return ft.Markdown(
            value=value,
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
            on_tap_link=_open_link,
            shrink_wrap=True,
            md_style_sheet=None if code else MARKDOWN_STYLE,
        )

    def _add_code(self, content: str):
        self.body.controls.append(
            ft.Container(
                content=ft.Row(
                    [self._md(content, code=True)],
                    scroll=ft.ScrollMode.AUTO,
                    wrap=False,
                ),
                data={"id": "code"},
            )
        )

    def _add_text(self, content: str):
        self.body.controls.append(
            ft.Container(
                content=self._md(content),
                data={"id": "text", "role": self.role},
            )
        )

    def _add_image(self, image_filepath: str):
        image = Image(image_path=image_filepath)

        self.body.controls.append(
            ft.Row(
                [
                    ft.Container(expand=1),
                    ft.Container(content=image, expand=4),
                    ft.Container(expand=1),
                ],
                expand=True,
            )
        )

    def _parse_content(self, content: str) -> list[dict]:
        parts = []
        last_pos = 0
        pattern = r'(```(?:\w+)?\s*\n.*?\n```)|(\[IMAGE:\s*(.*?)\])|(\[MOOD:\s*(.*?)\])'

        for m in re.finditer(pattern, content, re.DOTALL):
            if m.start() > last_pos:
                parts.append({"type": "text", "value": content[last_pos:m.start()].strip()})
            if m.group(1) is not None:
                parts.append({"type": "code", "value": m.group(1)})
            elif m.group(3) is not None:
                parts.append({"type": "image", "value": m.group(3).strip()})
            elif m.group(5) is not None:
                parts.append({"type": "mood", "value": m.group(5).strip()})
            last_pos = m.end()

        if last_pos < len(content):
            parts.append({"type": "text", "value": content[last_pos:].strip()})
        return parts


class OneLineBubble(ft.Container):
    def __init__(self, text: str = "", data=None, on_clicked=None, **kwargs):
        self.on_clicked = on_clicked
        self.label = ft.Text(text, text_align=ft.TextAlign.CENTER)
        super().__init__(
            content=self.label,
            alignment=ft.Alignment.CENTER,
            on_click=self._on_click,
            data=data,
            **STYLES["one_line_bubble"],
            **kwargs,
        )

    def set(self, text, data=None):
        self.label.value = text
        self.data = data

    def _on_click(self, e):
        if self.on_clicked:
            self.on_clicked(self.label.value, self.data)