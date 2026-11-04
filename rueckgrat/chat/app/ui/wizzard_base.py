import os
import flet as ft
from app.ui import theme

from app.ui import BasePage
from app.ui.widgets import Header

LABEL_WIDTH = 80
ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"


def wizard_row(label, control, description: str = None):
    row = ft.Row(
        [
            ft.Container(
                content=ft.Text(label, color=theme.TEXT_LABEL),
                width=LABEL_WIDTH,
                padding=ft.Padding.only(top=12),
                alignment=ft.Alignment.TOP_LEFT,
            ),
            ft.Container(
                content=control, 
                expand=False if description else True,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=12,
    )

    if description:
        row.controls.append(ft.Container(
                            content=ft.Text(description, color=theme.TEXT_LABEL),
                            expand=True,
                            alignment=ft.Alignment.TOP_LEFT,
                        ))

    return row


class WizardPage(BasePage):
    """header, a headline, one form and the buttons below it. subclasses fill the form in on_enter and handle on_submit"""

    show_cancel = False   # the cancel button is shown together with the submit button

    def __init__(self, navigator):
        super().__init__(navigator)
        self.header = Header(navigator, False)
        self.header.on_go_back = self.on_go_back
        self.title_text = ft.Text("", style=theme.STYLES["section_heading"])
        self.subtitle_text = ft.Text("", color=theme.TEXT_LABEL, visible=False)
        self.content_slot = ft.Container(expand=True)
        self.submit_btn = ft.Button("...", on_click=self.on_submit, expand=True, **theme.STYLES["button"])
        self.cancel_btn = ft.Button("Cancel", on_click=self.on_cancel, expand=True, visible=False, **theme.STYLES["button"])

        self.controls = [
            ft.Container(
                margin=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.header,
                        self.title_text,
                        self.subtitle_text,
                        self.content_slot,
                        ft.Row(controls=[self.cancel_btn, self.submit_btn]),
                    ],
                ),
            )
        ]

    def on_go_back(self, e=None):
        if not self.navigator.back():
            self.navigator("contacts")

    def on_cancel(self, e=None):
        self.on_go_back()

    def on_submit(self, e=None):
        pass

    def _show(self, content, button_text: str = None, title: str = "", subtitle: str = ""):
        self.title_text.value = title
        self.subtitle_text.value = subtitle
        self.subtitle_text.visible = bool(subtitle)
        self.content_slot.content = content
        self.submit_btn.visible = button_text is not None
        self.submit_btn.content = button_text or ""
        self.cancel_btn.visible = self.show_cancel and button_text is not None
        self.update()
