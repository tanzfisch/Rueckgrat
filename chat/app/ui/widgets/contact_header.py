from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, QSize, Signal
from app.utils import Contact
from pathlib import Path
from .settings import SettingsDialog

class ContactHeader(QWidget):
    go_back = Signal()
    open_profile = Signal()

    def __init__(self, selected_contact: bool=True, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignLeft)

        self.back_btn = QPushButton()
        self.back_btn.setObjectName("flatButton")
        self.back_btn.setIcon(QIcon("app/icons/back_light.png"))
        self.back_btn.setIconSize(QSize(24, 24))
        self.back_btn.setFixedSize(40, 40)
        self.back_btn.clicked.connect(self.handle_go_back)

        self.profile_label = QLabel()
        pixmap = QPixmap("app/icons/profile_light.png")
        self.profile_label.setScaledContents(True)
        self.profile_label.setPixmap(pixmap)
        self.profile_label.setFixedSize(40, 40)

        self.contact_name = QLabel("...")

        self.menu_btn = QPushButton()
        self.menu_btn.setObjectName("flatButton")
        self.menu_btn.setIcon(QIcon("app/icons/menu_light.png"))
        self.menu_btn.setIconSize(QSize(24, 24))
        self.menu_btn.setFixedSize(40, 40)
        self.menu_btn.clicked.connect(self.handle_open_menu)

        if selected_contact:
            layout.addWidget(self.back_btn)
            layout.addWidget(self.profile_label)
            layout.addWidget(self.contact_name)     

        layout.addStretch() 
        layout.addWidget(self.menu_btn)   

    def set_contact(self, contact: Contact):
        self.contact = contact

        self.contact_name.setText(self.contact.get_name())
        profile_image_name = self.contact.get_latest_profile_image_name()
        profile_image_path = Path("cache/images") / profile_image_name
        self.profile_label.setPixmap(QPixmap(str(profile_image_path)))

    def mousePressEvent(self, event):
        self.open_profile.emit()
        super().mousePressEvent(event)        

    def handle_go_back(self):
        self.go_back.emit()

    def handle_open_menu(self):
        SettingsDialog.open()