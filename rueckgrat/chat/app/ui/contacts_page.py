import json
import flet as ft
from pathlib import Path
from app.ui.theme import STYLES

from app.ui import BasePage
from app.ui.widgets import OneLineBubble, ContactCard, ContactHeader
from app.utils import Hub, Contact, Paths
from app.common import get_logger, Utils

logger = get_logger()

class ContactsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.contact_header = ContactHeader(navigator, False, False)
        self.list_view = ft.ListView(expand=True, spacing=8, padding=8)
        self.import_contact_picker = ft.FilePicker()
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

        Hub.register_incomming_message(self.on_incomming_message)

    def on_incomming_message(self, msg: dict):
        logger.debug(f"incomming message\n{Utils.pretty_print(msg)}")
        try:
            if "new_contact" in msg:
                self.load_contacts()
        except Exception as e:
            logger.error(f"failed to handle incomming message: {e}")

    def did_mount(self):
        if self.import_contact_picker not in self.page.services:
            self.page.services.append(self.import_contact_picker)

    def on_enter(self, **kwargs):
        self.load_contacts()

    def on_leave(self):
        Hub.unregister_incomming_message(self.on_incomming_message)

    def _on_add_contact(self, text=None, data=None):
        self.navigator("profile_wizz")

    def _on_import_contact(self, text=None, data=None):
        self.page.run_task(self._pick_import)

    async def _pick_import(self):
        files = await self.import_contact_picker.pick_files(
            dialog_title="Import Profile",
            initial_directory=str((Path.cwd() / "../../characters").resolve()),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["json"],
        )
        if not files or not files[0].path:
            return
        try:
            with open(files[0].path, "r") as file:
                data = json.load(file)
            contact_id = Hub.create_contact()
            Hub.update_contact(contact_id, data)
            self.load_contacts()
        except Exception as ex:
            logger.error(f"failed to load profile: {repr(ex)}")        

    def load_contacts(self):
        contacts = Hub.get_contacts()
        items = [
            ft.Row(
                controls=[
                    OneLineBubble("new", on_clicked=self._on_add_contact, expand=True),
                    OneLineBubble("import", on_clicked=self._on_import_contact, expand=True),
                ]
            )
        ]

        for contact_dict in contacts:
            contact = Contact(contact_dict)
            profile_image_name = contact.get_latest_profile_image_name()
            if profile_image_name:
                profile_image_path = Paths.get_image_path() / profile_image_name
                if not profile_image_path.exists():
                    Hub.download_file(f"images/{profile_image_name}", Paths.get_image_path(), 0)

            cid = contact.get_id()
            card = ContactCard(contact)
            card.on_clicked = lambda e, i=cid: self.on_contact_clicked(i)

            items.append(
                ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(content=card, expand=True),
                        ft.Column(
                            spacing=0,
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.EDIT,
                                    width=40,
                                    height=40,
                                    on_click=lambda e, i=cid: self.edit_contact(i),
                                    style=STYLES["icon_button"]["style"],
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE,
                                    width=40,
                                    height=40,
                                    on_click=lambda e, i=cid: self.delete_contact(i),
                                    style=STYLES["icon_button"]["style"],
                                ),
                            ],
                        ),
                    ],
                )
            )

        self.list_view.controls = items
        self.list_view.update()

        if self.page:
            self.page.update()

    def on_contact_clicked(self, contact_id):
        self.navigator("conversations", contact_id=contact_id)

    def delete_contact(self, contact_id):
        def confirm(e):
            self.page.pop_dialog()
            Hub.delete_contact(contact_id)
            self.load_contacts()

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Delete contact"),
                content=ft.Text("Are you sure you want to delete this contact?"),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog(), style=STYLES["button"]["style"]),
                    ft.TextButton("Delete", on_click=confirm, style=STYLES["button"]["style"]),
                ],
            )
        )

    def edit_contact(self, contact_id):
        self.navigator("profile", contact_id=contact_id)