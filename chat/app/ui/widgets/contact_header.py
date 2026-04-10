from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, QSize, Signal
from app.utils import Contact
from pathlib import Path

class ContactHeader(QWidget):
    go_back = Signal()
    open_profile = Signal()

    def __init__(self, parent=None):
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

        layout.addWidget(self.back_btn)
        layout.addWidget(self.profile_label)
        layout.addWidget(self.contact_name)        

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