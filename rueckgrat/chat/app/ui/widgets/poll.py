import flet as ft
from app.ui import theme

from app.common import get_logger
logger = get_logger()


class PollView(ft.Column):
    """the poll bubble under an assistant answer. single mode: a tap selects one option.
    multi mode: taps toggle options. in both modes Confirm submits the selection. on_submit(chosen) returns True when the answer was sent,
    the poll is locked then and shows the choice. a poll with "chosen" (answered before) starts locked"""
    def __init__(self, poll: dict, on_submit=None):
        super().__init__(spacing=8, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.poll = poll
        self.on_submit = on_submit
        self.multi = poll.get("mode") == "multi"
        self.options = list(poll.get("options") or [])
        self.selected: list[str] = []
        self.locked = bool(poll.get("chosen"))
        if self.locked:
            self.selected = [option for option in self.options if option in poll["chosen"]]
        self.confirm_btn = ft.Button("Confirm", on_click=self._on_confirm, style=theme.STYLES["button"]["style"])
        self._build()

    def _icon(self, selected: bool) -> str:
        if self.multi:
            return ft.Icons.CHECK_BOX if selected else ft.Icons.CHECK_BOX_OUTLINE_BLANK
        return ft.Icons.CHECK_CIRCLE if selected else ft.Icons.RADIO_BUTTON_UNCHECKED

    def _option_tile(self, option: str) -> ft.Container:
        selected = option in self.selected
        color = theme.ON_ACCENT if selected else theme.TEXT
        return ft.Container(
            bgcolor=theme.TEAL_FILL if selected else theme.SURFACE,
            border_radius=theme.RADIUS,
            padding=10,
            opacity=0.5 if self.locked and not selected else 1.0,
            on_click=None if self.locked else (lambda e, o=option: self._on_option(o)),
            content=ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(self._icon(selected), size=20, color=color),
                    ft.Text(option, color=color, expand=True, font_family=theme.TEXT_FONT, font_family_fallback=theme.EMOJI_FALLBACK),
                ],
            ),
        )

    def _build(self):
        controls = [ft.Text(self.poll.get("question", ""), weight=ft.FontWeight.BOLD, color=theme.TEXT,
                            font_family=theme.TEXT_FONT, font_family_fallback=theme.EMOJI_FALLBACK)]
        controls += [self._option_tile(option) for option in self.options]
        if not self.locked:
            self.confirm_btn.disabled = not self.selected
            self.confirm_btn.opacity = 0.5 if self.confirm_btn.disabled else 1.0
            controls.append(ft.Row([self.confirm_btn], alignment=ft.MainAxisAlignment.END))
        self.controls = controls

    def _refresh(self):
        self._build()
        self.update()   # after a tap, the poll is on the page

    def _on_option(self, option: str):
        if self.locked:
            return
        if not self.multi:
            self.selected = [option]
        elif option in self.selected:
            self.selected.remove(option)
        else:
            self.selected.append(option)
        self.selected.sort(key=self.options.index)
        self._refresh()

    def _on_confirm(self, e=None):
        if self.selected and not self.locked:
            self._submit()

    def _submit(self):
        try:
            sent = self.on_submit(list(self.selected)) if self.on_submit else False
        except Exception as e:
            logger.error(f"failed to submit poll: {repr(e)}")
            sent = False
        if sent:
            self.locked = True   # not sent: the poll stays open with its selection
        self._refresh()
