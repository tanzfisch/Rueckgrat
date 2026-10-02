import flet as ft
from app.ui.theme import STYLES

from app.ui import BasePage
from app.ui.widgets import RowSelector, ContactHeader
from app.utils import RueckgratConfig


class NetworkSettingsPage(ft.Column):
    def __init__(self):
        super().__init__(expand=True)
        self.on_ok = None
        self.on_cancel = None
        self.config = RueckgratConfig()

        self.host_input = ft.TextField(label="Host", width=float("inf"), value=self.config.host, **STYLES["field"])
        self.port_input = ft.TextField(label="Port", width=float("inf"), value=self.config.port, **STYLES["field"])

        self.controls = [
            self.host_input,
            self.port_input,
            ft.Container(expand=True),
            ft.Row(
                controls=[
                    ft.Button("Save", expand=True, on_click=self._ok, style=STYLES["button"]["style"]),
                    ft.Button("Cancel", expand=True, on_click=self._cancel, style=STYLES["button"]["style"]),
                ]
            ),
        ]

    def _ok(self, e=None):
        self.config.host = self.host_input.value or ""
        self.config.port = self.port_input.value or ""
        if self.on_ok:
            self.on_ok()

    def _cancel(self, e=None):
        self.host_input.value = self.config.host
        self.port_input.value = self.config.port
        self.host_input.update()
        self.port_input.update()
        if self.on_cancel:
            self.on_cancel()


class UserProfileSettingsPage(ft.Column):
    def __init__(self, navigator):
        super().__init__(expand=True)
        self.navigator = navigator
        self.controls = [
            ft.Button("edit", on_click=self.on_click_user_profile, style=STYLES["button"]["style"]),
            ft.Container(expand=True),
        ]

    def on_click_user_profile(self, e=None):
        self.navigator("profile_wizz", user_profile_mode=True)


class SettingsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.contact_header = ContactHeader(navigator, False, True)
        self.contact_header.on_go_back = self.on_go_back

        self.profile_page = UserProfileSettingsPage(self.navigator)
        self.network_page = NetworkSettingsPage()
        self.content_slot = ft.Container(content=self.profile_page, expand=True)

        self.page_selector = RowSelector(["Profile", "Network"], True, 1)
        self.page_selector.on_selection_changed = self.on_page_changed
        self.page_selector.select("Profile")

        self.controls = [
            ft.Container(
                padding=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.contact_header,
                        ft.Row(
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                            controls=[
                                ft.Container(
                                    width=100,
                                    content=ft.Column(
                                        controls=[
                                            self.page_selector,
                                            ft.Container(expand=True),
                                        ]
                                    ),
                                ),
                                self.content_slot,
                            ],
                        ),
                    ],
                ),
            )
        ]

    def on_go_back(self, e=None):
        self.navigator("contacts")

    def on_page_changed(self, page_name: str):
        pages = {"Profile": self.profile_page, "Network": self.network_page}
        self.content_slot.content = pages[page_name]
        self.content_slot.update() 