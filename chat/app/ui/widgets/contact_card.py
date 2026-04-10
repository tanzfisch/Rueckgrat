from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFrame, QSizePolicy, QHBoxLayout)
from PySide6.QtCore import Qt, Signal
from .image import Image
from app.utils import Contact
from pathlib import Path

from common import Logger
logger = Logger(__name__).get_logger()

class ContactCard(QFrame):
    clicked = Signal(int)

    def __init__(self, contact: Contact):
        super().__init__()
        self.contact = contact

        self.setObjectName("contact_card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)        
        self.setCursor(Qt.PointingHandCursor)

        profile_image_name = self.contact.get_latest_profile_image_name()
        profile_image_path = Path("cache/images") / profile_image_name
               
        layout = QHBoxLayout(self)
        profile_image = Image(profile_image_path)
        profile_image.setFixedSize(200, 200)
        profile_image.setScaledContents(True)
        layout.addWidget(profile_image)

        wrapper = QWidget()
        wrapper.setObjectName("transparent")
        label_layout = QVBoxLayout(wrapper)
        layout.addWidget(wrapper)

        name_label = QLabel(self.contact.get_name())
        label_layout.addWidget(name_label)

        traits_label = QLabel(self.contact.get_role())
        traits_label.setWordWrap(True)
        label_layout.addWidget(traits_label)

        purpose_label = QLabel(self.contact.get_persona())
        purpose_label.setWordWrap(True)
        label_layout.addWidget(purpose_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.contact.get_id())
        super().mousePressEvent(event)

