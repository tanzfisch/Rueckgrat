from PySide6.QtWidgets import (
    QVBoxLayout
)

from app.ui import BasePage
from app.ui.settings_page import NetworkSettingsPage

from common import Logger
logger = Logger(__name__).get_logger()

class InitialSettingsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20,20,20,20)

        self.network_page = NetworkSettingsPage()
        main_layout.addWidget(self.network_page)

        self.network_page.ok_clicked.connect(self.on_settings_accepted)

    def on_settings_accepted(self):
        self.navigator("login")