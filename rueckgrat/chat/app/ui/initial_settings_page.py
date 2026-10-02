from app.ui import BasePage
from app.ui.settings_page import NetworkSettingsPage
import flet as ft


class InitialSettingsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.spacing = 0
        self.network_page = NetworkSettingsPage()
        self.network_page.on_ok = self.on_settings_accepted
        self.controls = [
            ft.Container(padding=20, expand=True, content=self.network_page)
        ]

    def on_settings_accepted(self, e=None):
        self.navigator("login")