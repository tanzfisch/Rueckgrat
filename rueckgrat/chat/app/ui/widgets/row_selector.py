import random
from typing import Dict, Any, Union, List
import flet as ft

from app.common import get_logger
from app.ui.theme import SURFACE_3, TEAL_FILL, TEXT

logger = get_logger()


class RowSelector(ft.Column):
    def __init__(
        self,
        options: Union[Dict[str, Any], List[str]],
        image_only: bool = True,
        max_columns: int = 5,
        on_selection_changed=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.buttons: list[ft.Container] = []
        self.selected = None
        self.on_selection_changed = on_selection_changed

        if isinstance(options, dict):
            items = list(options.items())
        elif isinstance(options, list):
            items = [(name, "") for name in options]
        else:
            logger.error("invalid parameter type")
            items = []

        for name, image in items:
            self.buttons.append(self._make_button(name, image, image_only))

        if max_columns <= 1:
            self.controls = self.buttons
        else:
            self.controls = [
                ft.Row(self.buttons[i : i + max_columns], spacing=8)
                for i in range(0, len(self.buttons), max_columns)
            ]

        self.spacing = 8
        self.tight = True
        self.horizontal_alignment = ft.CrossAxisAlignment.STRETCH

    def _make_button(self, name: str, image: str, image_only: bool) -> ft.Container:
        if image and image_only:
            content = ft.Image(src=image, width=36, height=36, fit=ft.BoxFit.CONTAIN)
        elif image:
            content = ft.Row(
                tight=True,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Image(src=image, width=36, height=36, fit=ft.BoxFit.CONTAIN),
                    ft.Text(name, color=TEXT),
                ],
            )
        else:
            content = ft.Text(name, color=TEXT, text_align=ft.TextAlign.CENTER)

        return ft.Container(
            content=content,
            data=name,
            padding=8,
            height=48,
            expand=True,
            alignment=ft.Alignment.CENTER,
            border_radius=12,
            bgcolor=SURFACE_3,
            border=ft.Border.all(2, ft.Colors.TRANSPARENT),
            on_click=self._on_click,
        )

    def _on_click(self, e):
        self.select(e.control.data)
        if self.on_selection_changed:
            self.on_selection_changed(self.selected)

    def _refresh(self):
        for btn in self.buttons:
            on = btn.data == self.selected
            btn.bgcolor = TEAL_FILL if on else SURFACE_3
            btn.border = ft.Border.all(2, TEAL_FILL if on else ft.Colors.TRANSPARENT)
            text = btn.content if isinstance(btn.content, ft.Text) else None
            if text is None and isinstance(btn.content, ft.Row):
                for c in btn.content.controls:
                    if isinstance(c, ft.Text):
                        text = c
                        break
            if text:
                text.color = TEXT
        if self.parent:
            self.update()

    def update_images(self, options: Dict[str, Any]):
        for btn in self.buttons:
            src = options.get(btn.data)
            if src:
                btn.content = ft.Image(src=src, width=36, height=36, fit=ft.BoxFit.CONTAIN)
        if self.parent:
            self.update()

    def select_random(self):
        if self.buttons:
            self.select(random.choice(self.buttons).data)

    def select(self, key: str):
        self.selected = key
        self._refresh()

    def unselect(self):
        self.selected = None
        self._refresh()

    def get_selected(self):
        return self.selected