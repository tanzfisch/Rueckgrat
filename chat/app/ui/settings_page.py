from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QStackedLayout,
    QWidget, QLineEdit, QFormLayout, QFileDialog, 
    QPushButton,
)

from app.ui import BasePage
from app.utils import RueckgratConfig
from app.ui.widgets import RowSelector, ContactHeader

from common import Logger
logger = Logger(__name__).get_logger()


class NetworkSettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.config = RueckgratConfig()

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        container = QWidget()
        layout.addWidget(container)
        self.form_layout = QFormLayout(container)
        self.form_layout.setSpacing(5)

        self.host_input = QLineEdit(self.config.host)
        self.form_layout.addRow("Host", self.host_input)

        self.port_input = QLineEdit(self.config.port)
        self.form_layout.addRow("Port", self.port_input)

        cert_container = QWidget()
        cert_layout = QHBoxLayout(cert_container)
        self.cert_input = QLineEdit(self.config.server_cert)
        cert_layout.addWidget(self.cert_input)
        browse_btn = QPushButton("Browse")        
        browse_btn.clicked.connect(self._browse_cert)
        cert_layout.addWidget(browse_btn)
        
        self.form_layout.addRow("Certificate", cert_container)

        layout.addStretch()

        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        ok_btn = QPushButton("Save")
        ok_btn.clicked.connect(self._ok)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._cancel)        
        btn_layout.addWidget(cancel_btn)

        layout.addWidget(btn_container)

    def _ok(self):
        self.config.host = self.host_input.text()
        self.config.port = self.port_input.text()
        self.config.server_cert = self.cert_input.text()

    def _cancel(self):
        self.host_input.setText(self.config.host)
        self.port_input.setText(self.config.port)
        self.cert_input.setText(self.config.server_cert)

    def _browse_cert(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Certificate")
        if path:
            self.cert_input.setText(path)        

class ProfilePage(QWidget):
    def __init__(self, navigator, parent=None):
        super().__init__(parent)        
        self.navigator = navigator

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        container = QWidget()
        layout.addWidget(container)
        self.form_layout = QFormLayout(container)
        self.form_layout.setSpacing(5)

        profile_button = QPushButton()
        profile_button.setText("edit")
        profile_button.clicked.connect(self.on_click_user_profile)
        self.form_layout.addRow("User Profile", profile_button)

        layout.addStretch()

    def on_click_user_profile(self):
        self.navigator("profile_wizz", user_profile_mode=True)

class SettingsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20,20,20,20)

        self.contact_header = ContactHeader(navigator, False, True)
        self.contact_header.go_back.connect(self.on_go_back)
        main_layout.addWidget(self.contact_header)        

        sub_container = QWidget()
        sub_layout = QHBoxLayout(sub_container)
        sub_layout.setContentsMargins(20,20,20,20)

        main_layout.addWidget(sub_container)

        selector_container = QWidget()
        selector_layout = QVBoxLayout(selector_container)
        sub_layout.addWidget(selector_container)
       
        pages = ["Profile", "Network"]

        self.page_selector = RowSelector(pages, True, 1)
        self.page_selector.selection_changed.connect(self.on_page_changed)
        selector_layout.addWidget(self.page_selector)
        selector_layout.addStretch()
        
        pages_container = QWidget()
        pages_layout = QVBoxLayout(pages_container)
        pages_layout.setContentsMargins(0,0,0,0)
        sub_layout.addWidget(pages_container)

        self.stack = QStackedLayout()
        self.stack.setContentsMargins(0,0,0,0)
        pages_layout.addLayout(self.stack)

        self.profile_page = ProfilePage(self.navigator)
        self.stack.addWidget(self.profile_page)

        self.network_page = NetworkSettingsPage()
        self.stack.addWidget(self.network_page)

        self.stack.setCurrentWidget(self.profile_page)

    def on_go_back(self):
        self.navigator("contacts")        

    def on_page_changed(self, page_name: str):
        pages = {
            "Profile": self.profile_page,
            "Network": self.network_page
        }
        self.stack.setCurrentWidget(pages[page_name])