import json
import flet as ft
from app.ui.theme import STYLES

from app.ui import BasePage
from app.ui.widgets import ContactHeader
from app.utils import Hub
from app.common import get_logger, Utils

logger = get_logger()


class ProfilePage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.contact_id = None

        self.contact_header = ContactHeader(navigator, False, True)
        self.contact_header.on_go_back = self.on_go_back

        self.name = ft.TextField(label="Name")
        self.male_radio = ft.Radio(value="male", label="Male")
        self.female_radio = ft.Radio(value="female", label="Female")
        self.gender_group = ft.RadioGroup(
            value="male",
            content=ft.Row(controls=[self.male_radio, self.female_radio]),
        )
        self.role = ft.TextField(label="Role", multiline=True, min_lines=3, max_lines=5)
        self.personality = ft.TextField(label="Persona", multiline=True, min_lines=3, max_lines=5)
        self.profile = ft.TextField(
            label="Profile",
            multiline=True,
            min_lines=8,
            max_lines=16,
        )
        self.file_picker = ft.FilePicker()

        self.controls = [
            self.contact_header,
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(
                    expand=True,
                    controls=[
                        ft.ListView(
                            expand=True,
                            spacing=12,
                            padding=12,
                            controls=[
                                self.name,
                                ft.Text("Gender"),
                                self.gender_group,
                                self.role,
                                self.personality,
                                self.profile,
                            ],
                        ),
                        ft.Column(
                            tight=True,
                            controls=[
                                ft.Button("Load", width=float("inf"), on_click=self._on_load, style=STYLES["button"]["style"]),
                                ft.Button("Export", width=float("inf"), on_click=self._on_export, style=STYLES["button"]["style"]),
                                ft.Row(
                                    controls=[
                                        ft.Button("Cancel", expand=True, on_click=self._on_cancel, style=STYLES["button"]["style"]),
                                        ft.Button("Save Profile", expand=True, on_click=self._on_save, style=STYLES["button"]["style"]),
                                    ]
                                ),
                            ],
                        ),
                    ],
                ),
            ),
        ]

    def did_mount(self):
        if self.file_picker not in self.page.services:
            self.page.services.append(self.file_picker)

    def on_go_back(self, e=None):
        self.navigator("contacts")

    def clear_form(self):
        self.name.value = ""
        self.role.value = ""
        self.personality.value = ""
        self.profile.value = ""
        self.set_gender("male")
        self.update()

    def fill_form(self, contact):
        self.name.value = Utils.get_nested_value(contact, ["identity", "name"], "")
        self.set_gender(Utils.get_nested_value(contact, ["identity", "gender"], ""))
        self.role.value = Utils.get_nested_value(contact, ["identity", "role"], "")
        self.personality.value = Utils.get_nested_value(contact, ["identity", "personality"], "")
        data = Utils.get_nested_value(contact, ["profile"], "")
        self.profile.value = json.dumps(data, indent=4)
        self.update()

    def load_profile(self):
        self.clear_form()
        if self.contact_id == -1:
            return
        self.fill_form(Hub.get_contact(self.contact_id))

    async def _on_load(self, e=None):
        files = await self.file_picker.pick_files(dialog_title="Import Profile")
        if not files or not files[0].path:
            return
        with open(files[0].path, "r") as file:
            self.fill_form(json.load(file))

    async def _on_export(self, e=None):
        path = await self.file_picker.save_file(dialog_title="Export Profile")
        if not path:
            return
        with open(path, "w") as file:
            json.dump(self.get_data(), file, indent=4)

    def _on_cancel(self, e=None):
        self.navigator("contacts")

    def _on_save(self, e=None):
        if self.contact_id == -1:
            self.contact_id = Hub.create_contact()
        Hub.update_contact(self.contact_id, self.get_data())
        self.navigator("contacts")

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        self.load_profile()

    def on_leave(self):
        pass

    def set_gender(self, gender: str):
        if not gender:
            return
        self.gender_group.value = gender.lower()

    def get_data(self):
        gender = self.gender_group.value or "male"
        profile = json.loads(self.profile.value or "{}")
        return {
            "identity": {
                "name": self.name.value or "",
                "gender": gender,
                "role": self.role.value or "",
                "personality": self.personality.value or "",
            },
            "profile": profile,
        }