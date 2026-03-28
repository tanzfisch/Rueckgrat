from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QSizePolicy, QPushButton, QHBoxLayout)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, Signal, QSize

from app.ui import BasePage
from app.ui.widgets import OneLineBubble, MessageBox
from app.utils import Backend

class ContactCard(QFrame):
    clicked = Signal(int)

    def __init__(self, contact):
        super().__init__()

        self.contact_id = contact.get("id")
        self.setObjectName("contact_card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)

        name_label = QLabel(contact.get("name", ""))
        layout.addWidget(name_label)

        traits_label = QLabel(contact.get("role", ""))
        traits_label.setWordWrap(True)
        layout.addWidget(traits_label)

        purpose_label = QLabel(contact.get("persona", ""))
        purpose_label.setWordWrap(True)
        layout.addWidget(purpose_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.contact_id)
        super().mousePressEvent(event)

class ContactsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.main_layout = QVBoxLayout(self)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.container = QWidget()
        self.contacts_layout = QVBoxLayout(self.container)
        self.contacts_layout.setAlignment(Qt.AlignTop)

        self.scroll_area.setWidget(self.container)
        self.main_layout.addWidget(self.scroll_area)

    def on_enter(self, **kwargs):
        self.load_contacts()

    def on_leave(self):
        pass          

    def add_contact(self):        
        self.navigator("profile", contact_id=-1)

    def load_contacts(self):
        # Clear existing widgets
        while self.contacts_layout.count():
            item = self.contacts_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        contacts = Backend.get_instance().get_contacts()

        add_contact_bubble = OneLineBubble("+")
        add_contact_bubble.clicked.connect(self.add_contact)
        self.contacts_layout.addWidget(add_contact_bubble)

        for contact in contacts:
            contact_card_container = QWidget()
            contact_card_layout = QHBoxLayout(contact_card_container)            

            card = ContactCard(contact)
            card.clicked.connect(self.on_contact_clicked)
            contact_card_layout.addWidget(card)

            button_container = QWidget()
            button_layout = QVBoxLayout(button_container)            

            edit_btn = QPushButton()
            edit_btn.setIcon(QIcon("app/icons/edit_light.png"))
            edit_btn.setIconSize(QSize(24, 24))
            edit_btn.setFixedSize(40, 40)
            button_layout.addWidget(edit_btn)
            edit_btn.clicked.connect(
                lambda checked=False, contact_id=contact["id"]: 
                self.edit_contact(contact_id)
            )  

            delete_btn = QPushButton()
            delete_btn.setIcon(QIcon("app/icons/bin.png"))
            delete_btn.setIconSize(QSize(24, 24))
            delete_btn.setFixedSize(40, 40)
            button_layout.addWidget(delete_btn)
            delete_btn.clicked.connect(
                lambda checked=False, contact_id=contact["id"]: 
                self.delete_contact(contact_id)
            )     
  
            contact_card_layout.addWidget(button_container)

            self.contacts_layout.addWidget(contact_card_container)

        self.contacts_layout.addStretch()

    def on_contact_clicked(self, contact_id):
        self.navigator("conversations", contact_id=contact_id)

    def delete_contact(self, contact_id):
        if MessageBox.open("Are you sure you want to delete this contact?"):
            Backend.get_instance().delete_contact(contact_id)

        self.load_contacts()        

    def edit_contact(self, contact_id):
        self.navigator("profile", contact_id=contact_id)