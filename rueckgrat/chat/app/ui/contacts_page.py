import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QPushButton, QHBoxLayout, QFileDialog
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, QSize

from app.ui import BasePage
from app.ui.widgets import OneLineBubble, MessageBox, ContactCard, ContactHeader
from app.utils import Hub, Contact, Paths


from app.common import get_logger
logger = get_logger()

class ContactsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.main_layout = QVBoxLayout(self)

        self.contact_header = ContactHeader(navigator, False, False)
        self.main_layout.addWidget(self.contact_header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.container = QWidget()
        self.contacts_layout = QVBoxLayout(self.container)
        self.contacts_layout.setSpacing(8)
        self.contacts_layout.setAlignment(Qt.AlignTop)

        self.scroll_area.setWidget(self.container)
        self.main_layout.addWidget(self.scroll_area)

    def on_enter(self, **kwargs):
        self.load_contacts()

    def on_leave(self):
        pass

    def _on_add_contact(self):
        self.navigator("profile_wizz")

    def _on_import_contact(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile", "../../characters", "Profile Files (*.json)")
        if path:
            with open(path, 'r') as file:
                try:
                    data = json.load(file)
                    contact_id = Hub.create_contact()
                    Hub.update_contact(contact_id, data)
                    self.navigator("contacts")
                except Exception as e:
                    logger.error(f"failed to load profile: {repr(e)}")
        
    def load_contacts(self):
        # Clear existing widgets
        while self.contacts_layout.count():
            item = self.contacts_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        contacts = Hub.get_contacts()

        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)

        add_btn = OneLineBubble("new")
        add_btn.clicked.connect(self._on_add_contact)
        buttons_layout.addWidget(add_btn)

        import_btn = OneLineBubble("import")
        import_btn.clicked.connect(self._on_import_contact)
        buttons_layout.addWidget(import_btn)

        container = QWidget()
        container.setLayout(buttons_layout)
        self.contacts_layout.addWidget(container)

        for contact_dict in contacts:
            contact = Contact(contact_dict)
            profile_image_name = contact.get_latest_profile_image_name()
            if profile_image_name:
                profile_image_path = Paths.get_image_path() / profile_image_name
                if not profile_image_path.exists():
                    Hub.download_file(f"images/{profile_image_name}", Paths.get_image_path(), 0)

            contact_card_container = QWidget()
            contact_card_layout = QHBoxLayout(contact_card_container)            
            contact_card_layout.setContentsMargins(0, 0, 0, 0)

            card = ContactCard(contact)
            card.clicked.connect(self.on_contact_clicked)
            contact_card_layout.addWidget(card)

            button_container = QWidget()
            button_layout = QVBoxLayout(button_container)            
            button_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            button_layout.setContentsMargins(0, 0, 0, 0)

            edit_btn = QPushButton()
            edit_btn.setIcon(QIcon("app/icons/edit_light.png"))
            edit_btn.setIconSize(QSize(24, 24))
            edit_btn.setFixedSize(40, 40)
            button_layout.addWidget(edit_btn)
            edit_btn.clicked.connect(
                lambda checked=False, contact_id=contact.get_id():
                self.edit_contact(contact_id)
            )  

            delete_btn = QPushButton()
            delete_btn.setIcon(QIcon("app/icons/bin.png"))
            delete_btn.setIconSize(QSize(24, 24))
            delete_btn.setFixedSize(40, 40)
            button_layout.addWidget(delete_btn)
            delete_btn.clicked.connect(
                lambda checked=False, contact_id=contact.get_id():
                self.delete_contact(contact_id)
            )     
  
            contact_card_layout.addWidget(button_container)

            self.contacts_layout.addWidget(contact_card_container)

        self.contacts_layout.addStretch()

    def on_contact_clicked(self, contact_id):
        self.navigator("conversations", contact_id=contact_id)

    def delete_contact(self, contact_id):
        if MessageBox.open("Are you sure you want to delete this contact?"):
            Hub.delete_contact(contact_id)

        self.load_contacts()        

    def edit_contact(self, contact_id):
        self.navigator("profile", contact_id=contact_id)