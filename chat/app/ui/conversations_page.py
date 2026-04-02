from PySide6.QtWidgets import (QWidget, QVBoxLayout, QScrollArea, QHBoxLayout, QPushButton)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, QSize

from app.ui import BasePage
from app.ui.widgets import MessageBox, OneLineBubble, ContactHeader
from app.utils import Backend, Contact

from common import Logger
logger = Logger(__name__).get_logger()

class ConversationsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.main_layout = QVBoxLayout(self)

        self.contact_header = ContactHeader()
        self.contact_header.go_back.connect(self.on_go_back)
        self.main_layout.addWidget(self.contact_header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.container = QWidget()
        self.conversations_layout = QVBoxLayout(self.container)
        self.conversations_layout.setAlignment(Qt.AlignTop)
        self.conversations_layout.setSpacing(8)

        self.scroll_area.setWidget(self.container)
        self.main_layout.addWidget(self.scroll_area)

    def on_go_back(self):
        self.navigator("contacts")        

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        contact = Contact(Backend.get_instance().get_contact(self.contact_id))
        self.contact_header.set_contact(contact)

        self.load_conversations()

    def on_leave(self):
        pass   

    def conversation_chosen(self, title: str, conversation_id: int):
        self.navigator("chat", contact_id=self.contact_id, conversation_id=conversation_id)

    def create_conversation(self):
        conversation_id = Backend.get_instance().create_conversation(self.contact_id)
        self.navigator("chat", contact_id=self.contact_id, conversation_id=conversation_id)

    def delete_conversation(self, conversation_id):
        if MessageBox.open("Are you sure you want to delete this conversation?"):
            Backend.get_instance().delete_conversation(conversation_id)

        self.load_conversations()

    def load_conversations(self):
        # Clear existing widgets
        while self.conversations_layout.count():
            item = self.conversations_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        conversations = Backend.get_instance().get_conversations(self.contact_id)

        start_bubble = OneLineBubble("+")
        start_bubble.setFixedHeight(40)
        start_bubble.clicked.connect(self.create_conversation)
        self.conversations_layout.addWidget(start_bubble)

        for conversation in conversations:
            conversation_container = QWidget()
            conversation_layout = QHBoxLayout(conversation_container)
            conversation_layout.setContentsMargins(0, 0, 0, 0)

            bubble = OneLineBubble(conversation["title"], conversation["id"])
            bubble.clicked.connect(self.conversation_chosen)
            conversation_layout.addWidget(bubble)
            
            delete_btn = QPushButton()
            delete_btn.setIcon(QIcon("app/icons/bin.png"))
            delete_btn.setIconSize(QSize(24, 24))
            delete_btn.setFixedSize(40, 40)
            conversation_layout.addWidget(delete_btn)
            delete_btn.clicked.connect(
                lambda checked=False, conversation_id=conversation["id"]: 
                self.delete_conversation(conversation_id)
            )            

            self.conversations_layout.addWidget(conversation_container)

        self.conversations_layout.addStretch()
