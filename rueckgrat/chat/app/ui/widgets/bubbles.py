import re
import flet as ft
from app.ui.theme import STYLES

from app.common import get_logger
logger = get_logger()


def _open_link(e):
    url = e.data
    if url:
        e.page.launch_url(url)


class ChatBubble(ft.Container):
    def __init__(self, role: str, content: str, image_filepath: str | None = None, **kwargs):
        self.body = ft.Column(spacing=8, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        super().__init__(
            content=self.body,
            data={"role": role, "id": "chatBubble"},
            **kwargs,
        )
        self.role = role
        self.image_filepath = image_filepath
        self.raw_content = ""
        self.image_ctrl = None
        self.append_content(content)

    def _clear(self):
        self.body.controls.clear()
        self.image_ctrl = None

    def clear_content(self):
        self.raw_content = ""

    def append_content(self, content: str):
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

    def set_fixed_width(self, width: int):
        if self.image_ctrl:
            self.width = int(width * 0.8)
        else:
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
        self.image_ctrl = ft.Image(src=image_filepath, fit=ft.BoxFit.CONTAIN)
        self.body.controls.append(self.image_ctrl)

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