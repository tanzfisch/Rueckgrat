import flet as ft
from app.ui import theme

from app.ui import BasePage
from app.ui.widgets import OneLineBubble, Header
from app.utils import Hub, Contact, Paths
from app.common import get_logger

logger = get_logger()


class ConversationsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.contact_id = None
        self._conversation_ids = set()     # the listed ones: a message in another one (a task's new conversation) reloads the list
        self.header = Header(navigator)
        self.header.on_go_back = self.on_go_back
        self.list_view = ft.ListView(expand=True, spacing=8, padding=8)
        self.controls = [self.header, self.list_view]

        self.controls = [
            ft.Container(
                margin=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[self.header, self.list_view],
                ),
            )
        ]    

    def on_go_back(self, e=None):
        self.navigator.back()

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        contact = Contact(Hub.get_contact(self.contact_id))
        self.header.set_contact(contact)
        self.load_conversations()
        Hub.register_incomming_message(self.on_incomming_message)

    def on_leave(self):
        Hub.unregister_incomming_message(self.on_incomming_message)

    def on_incomming_message(self, msg: dict):
        """a message in a conversation that is not listed: the hub made it (a task or the companion wrote while the
        contact had no conversation), the list is loaded again. one of another contact's only costs a reload"""
        try:
            chat = msg.get("chat")
            if chat and chat.get("conversation_id") not in self._conversation_ids:
                self.load_conversations()
        except Exception as e:
            logger.error(f"failed to handle incomming message: {e}")

    def conversation_chosen(self, title: str, conversation_id: int):
        self.navigator("chat", contact_id=self.contact_id, conversation_id=conversation_id)

    def create_conversation(self, e=None):
        conversation_id = Hub.create_conversation(self.contact_id)
        self.navigator("chat", contact_id=self.contact_id, conversation_id=conversation_id)

    def delete_conversation(self, conversation_id):
        def confirm(e):
            self.page.pop_dialog()
            Paths.remove_cached_images(Hub.delete_conversation(conversation_id))
            self.load_conversations()

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Delete conversation"),
                content=ft.Text("Are you sure you want to delete this conversation?"),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog(), style=theme.STYLES["button"]["style"]),
                    ft.TextButton("Delete", on_click=confirm, style=theme.STYLES["button"]["style"]),
                ],
            )
        )

    def load_conversations(self):
        conversations = Hub.get_conversations(self.contact_id)
        self._conversation_ids = {conversation["id"] for conversation in conversations}
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