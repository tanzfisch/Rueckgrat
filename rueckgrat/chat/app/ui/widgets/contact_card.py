import flet as ft
from app.utils import Contact, Paths

from app.common import get_logger
logger = get_logger()


class ContactCard(ft.Container):
    def __init__(self, contact: Contact, on_clicked=None, **kwargs):
        self.contact = contact
        self.on_clicked = on_clicked

        profile_image_name = self.contact.get_latest_profile_image_name()
        profile_image_path = (
            str(Paths.get_image_path() / profile_image_name)
            if profile_image_name
            else ""
        )

        profile_image = ft.Image(
            src=profile_image_path or None,
            width=150,
            height=150,
            fit=ft.BoxFit.COVER,
        )

        labels = ft.Column(
            [
                ft.Text(self.contact.get_name()),
                ft.Text(self.contact.get_role()),
                ft.Text(self.contact.get_persona()),
            ],
            spacing=4,
            expand=True,
            tight=True,
        )

        super().__init__(
            content=ft.Row([profile_image, labels], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            data={"id": "contact_card"},
            ink=True,
            on_click=self._on_click,
            **kwargs,
        )

    def _on_click(self, e):
        if self.on_clicked:
            self.on_clicked(self.contact.get_id())