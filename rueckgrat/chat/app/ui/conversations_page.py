import flet as ft
from app.ui.theme import STYLES

from app.ui import BasePage
from app.ui.widgets import OneLineBubble, ContactHeader
from app.utils import Hub, Contact
from app.common import get_logger

logger = get_logger()


class ConversationsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.contact_id = None
        self.contact_header = ContactHeader(navigator)
        self.contact_header.on_go_back = self.on_go_back
        self.list_view = ft.ListView(expand=True, spacing=8, padding=8)
        self.controls = [self.contact_header, self.list_view]

        self.controls = [
            ft.Container(
                margin=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[self.contact_header, self.list_view],
                ),
            )
        ]    

    def on_go_back(self, e=None):
        self.navigator("contacts")

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        contact = Contact(Hub.get_contact(self.contact_id))
        self.contact_header.set_contact(contact)
        self.load_conversations()

    def on_leave(self):
        pass

    def conversation_chosen(self, title: str, conversation_id: int):
        self.navigator("chat", contact_id=self.contact_id, conversation_id=conversation_id)

    def create_conversation(self, e=None):
        conversation_id = Hub.create_conversation(self.contact_id)
        self.navigator("chat", contact_id=self.contact_id, conversation_id=conversation_id)

    def delete_conversation(self, conversation_id):
        def confirm(e):
            self.page.pop_dialog()
            Hub.delete_conversation(conversation_id)
            self.load_conversations()

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Delete conversation"),
                content=ft.Text("Are you sure you want to delete this conversation?"),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog(), style=STYLES["button"]["style"]),
                    ft.TextButton("Delete", on_click=confirm, style=STYLES["button"]["style"]),
                ],
            )
        )

    def load_conversations(self):
        conversations = Hub.get_conversations(self.contact_id)
        start_bubble = OneLineBubble("+")
        start_bubble.height = 40
        start_bubble.on_click = self.create_conversation

        items = [start_bubble]
        for conversation in conversations:
            title = conversation["title"]
            cid = conversation["id"]
            bubble = OneLineBubble(title, cid)
            bubble.on_click = lambda e, t=title, i=cid: self.conversation_chosen(t, i)
            items.append(
                ft.Row(
                    controls=[
                        ft.Container(content=bubble, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            icon_size=24,
                            width=40,
                            height=40,
                            on_click=lambda e, i=cid: self.delete_conversation(i),
                        ),
                    ]
                )
            )

        self.list_view.controls = items
        self.list_view.update()