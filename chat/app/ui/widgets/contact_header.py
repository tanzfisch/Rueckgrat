from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, QSize, Signal

class ContactHeader(QWidget):
    go_back = Signal()
    open_profile = Signal()

    def __init__(self, contact_name: str="", parent=None):
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

        self.contact_name = QLabel(contact_name)

        layout.addWidget(self.back_btn)
        layout.addWidget(self.profile_label)
        layout.addWidget(self.contact_name)        

    def set_name(self, contact_name: str):
        self.contact_name.setText(contact_name)

    def mousePressEvent(self, event):
        self.open_profile.emit()
        super().mousePressEvent(event)        

    def handle_go_back(self):
        self.go_back.emit()