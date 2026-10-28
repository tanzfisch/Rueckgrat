import asyncio
import copy
import json
from pathlib import Path
import flet as ft
from app.ui.theme import STYLES

from app.ui import BasePage
from app.ui.gallery_page import GalleryPage, broken_image_fallback
from app.ui.widgets import Header, Image, VoiceSelector
from app.utils import Contact, Hub, Paths
from app.common import get_logger, Utils, IMAGE_STYLE_OPTIONS, IMAGE_STYLE_ICONS

logger = get_logger()

IMAGE_SIZE = 120
IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp"]   # what the hub accepts

PROFILE_SECTIONS = [
    ("Story", [
        ("Background", ["background_hook"], "text"),
        ("Relationship to you", ["relationship"], "text"),
        ("Body language", ["body_language"], "text"),
        ("Style", ["style"], "text"),
    ]),
    ("Objectives", [
        ("Primary objective", ["objectives", "primary"], "text"),
        ("Secondary objectives (one per line)", ["objectives", "secondary"], "list"),
    ]),
    ("Interaction", [
        ("Tone", ["interaction_style", "tone"], "text"),
        ("Engagement", ["interaction_style", "engagement"], "text"),
        ("Quirks (one per line)", ["interaction_style", "quirks"], "list"),
    ]),
    ("Appearance", [
        ("Image style", ["appearance", "image_style"], "select"),
        ("General", ["appearance", "general"], "text"),
        ("Face", ["appearance", "face"], "text"),
        ("Hair", ["appearance", "hair"], "text"),
        ("Skin", ["appearance", "skin"], "text"),
        ("Upper body", ["appearance", "upper_body"], "text"),
        ("Body", ["appearance", "body"], "text"),
    ]),
    ("Profile picture setting", [
        ("Location", ["profile_picture_context", "location"], "text"),
        ("Topic", ["profile_picture_context", "topic"], "text"),
        ("Action", ["profile_picture_context", "assistant", "action"], "text"),
        ("Head", ["profile_picture_context", "assistant", "head"], "text"),
        ("Upper body clothing", ["profile_picture_context", "assistant", "upper_body"], "text"),
        ("Lower body clothing", ["profile_picture_context", "assistant", "body"], "text"),
    ]),
    ("Image Generation", [
        ("Seed", ["image_parameters", "seed"], "long"),
        ("Steps", ["image_parameters", "steps"], "long"),
        ("Cfg", ["image_parameters", "cfg"], "float"),
    ]),    
]

SELECT_OPTIONS = {
    ("appearance", "image_style"): IMAGE_STYLE_OPTIONS,
}

# optional images for "select" fields, keyed by key path: {stored value: image src shown in front of the option}
SELECT_ICONS = {
    ("appearance", "image_style"): IMAGE_STYLE_ICONS,
}


def _option_image(src: str | None) -> ft.Control | None:
    # small image in front of a dropdown option, None means no leading element.
    # a missing file shows an empty box of the same size, so the option texts stay aligned
    if not src:
        return None
    return ft.Image(src=src, width=32, height=32, fit=ft.BoxFit.COVER, border_radius=4,
                    error_content=ft.Container(width=32, height=32))


def _select_field(label: str, path: list[str]) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        options=[
            ft.DropdownOption(
                key=option,
                text=f"{option.replace('_', ' ')}: {description}",
                leading_icon=_option_image(SELECT_ICONS.get(tuple(path), {}).get(option)),
            )
            for option, description in SELECT_OPTIONS[tuple(path)].items()
        ],
        expand=True,
        filled=True,
        fill_color="#2C2C2C",
    )


def _text_field(label: str, kind: str) -> ft.TextField:
    if kind == "long":
        return ft.TextField(
            label=label, 
            multiline=True, 
            min_lines=1, 
            max_lines=None,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
        )
    elif kind == "float":
        return ft.TextField(
            label=label, 
            multiline=True, 
            min_lines=1, 
            max_lines=None,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.InputFilter(
                allow=True,
                regex_string=r"^[0-9]*\.?[0-9]*$",
                replacement_string="",
            ),
        )    
    else:
        return ft.TextField(label=label, multiline=True, min_lines=1, max_lines=None)


def _set_nested_value(data: dict, keys: list[str], value):
    for key in keys[:-1]:
        if not isinstance(data.get(key), dict):
            data[key] = {}
        data = data[key]
    data[keys[-1]] = value


class ProfilePage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.contact_id = None

        self.header = Header(navigator, False, True)
        self.header.on_go_back = self.on_go_back

        self.name = _text_field("Name", "text")
        self.male_radio = ft.Radio(value="male", label="Male")
        self.female_radio = ft.Radio(value="female", label="Female")
        self.gender_group = ft.RadioGroup(
            value="male",
            content=ft.Row(controls=[self.male_radio, self.female_radio]),
        )
        self.role = _text_field("Role", "text")
        self.personality = _text_field("Persona", "text")
        self.age = _text_field("Age", "text")
        self.voice_selector = VoiceSelector()
        # a pending choice, Save Profile sends it. hidden for a new contact
        self.companion_switch = ft.Switch(label="Companion (plans its own day, may write first)", active_color="#0D7377", visible=False)
        self.companion_loaded = False   # the hub's state, a different switch value is sent on save

        # original profile dict, so fields without a form entry survive a save
        self.profile_base = {}
        self.profile_fields = []  # (key path, kind, TextField)
        profile_controls = []
        for section, fields in PROFILE_SECTIONS:
            profile_controls.append(ft.Text(section, weight=ft.FontWeight.BOLD, size=16))
            for label, path, kind in fields:
                field = _select_field(label, path) if kind == "select" else _text_field(label, kind)
                self.profile_fields.append((path, kind, field))
                profile_controls.append(field)
        self.file_picker = ft.FilePicker()

        # the contact's current profile image, a tap on it or on the pen changes it. hidden for a new contact
        self.image_slot = ft.Container(
            width=IMAGE_SIZE,
            height=IMAGE_SIZE,
            border_radius=8,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            alignment=ft.Alignment.CENTER,
            on_click=self._on_edit_image,
        )
        self.image_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            visible=False,
            controls=[
                ft.Stack(
                    width=IMAGE_SIZE,
                    height=IMAGE_SIZE,
                    controls=[
                        self.image_slot,
                        ft.Container(
                            right=0,
                            bottom=0,
                            border_radius=20,
                            bgcolor=ft.Colors.with_opacity(0.6, ft.Colors.BLACK),
                            content=ft.IconButton(ft.Icons.EDIT, icon_size=18, tooltip="Change image", on_click=self._on_edit_image),
                        ),
                    ],
                ),
            ],
        )

        self.controls = [
            
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.header,
                        ft.ListView(
                            expand=True,
                            spacing=12,
                            padding=12,
                            controls=[
                                self.image_row,
                                self.name,
                                ft.Row(
                                    tight=True,
                                    controls=[
                                        ft.Text("Gender"),
                                        self.gender_group,
                                    ]
                                ),
                                self.age,
                                self.companion_switch,
                                ft.Row(
                                    controls=[
                                        ft.Text("Voice"),
                                        ft.Container(content=self.voice_selector, expand=True),
                                    ]
                                ),
                                self.role,
                                self.personality,
                                *profile_controls,
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
        self.age.value = ""
        self.profile_base = {}
        for _, kind, field in self.profile_fields:
            field.value = None if kind == "select" else ""
        self.set_gender("male")
        self.voice_selector.set_current_voice("")
        self.image_row.visible = False
        self.companion_switch.visible = False
        self.companion_switch.value = self.companion_loaded = False
        self.update()

    def fill_form(self, contact):
        self.name.value = Utils.get_nested_value(contact, ["identity", "name"], "")
        self.set_gender(Utils.get_nested_value(contact, ["identity", "gender"], ""))
        self.role.value = Utils.get_nested_value(contact, ["identity", "role"], "")
        self.personality.value = Utils.get_nested_value(contact, ["identity", "personality"], "")
        self.age.value = Utils.get_nested_value(contact, ["identity", "age"], "")
        profile = Utils.get_nested_value(contact, ["profile"], {}) or {}
        self.profile_base = copy.deepcopy(profile)
        for path, kind, field in self.profile_fields:
            value = Utils.get_nested_value(profile, path, "")
            if kind == "select":
                # unknown or missing values show as "nothing selected" instead of an invalid option
                field.value = value if value in SELECT_OPTIONS[tuple(path)] else None
                continue
            if kind == "list":
                value = "\n".join(str(v) for v in value) if isinstance(value, list) else str(value or "")
            field.value = value if isinstance(value, str) else json.dumps(value)
        self.voice_selector.set_current_voice(Utils.get_nested_value(profile, ["tts_parameters", "voice_id"], ""))
        self.update()

    def load_profile(self):
        self.clear_form()
        if self.contact_id == -1:
            return
        contact = Hub.get_contact(self.contact_id)
        self.fill_form(contact)
        # only the hub sets the flag (PUT /contacts/{id}/companion), so it is read here and not in fill_form: Load must not change it
        self.companion_loaded = bool(Utils.get_nested_value(contact, ["profile", "companion"], False))
        self.companion_switch.value = self.companion_loaded
        self.companion_switch.visible = True
        self.companion_switch.update()
        self.image_row.visible = True
        self._show_image(Contact(contact or {}).get_latest_profile_image_name())

    def _show_image(self, file_key: str):
        # file names are content hashes, so a cached file is never stale: a new image is a new name
        if not file_key:
            self.image_slot.content = ft.Icon(ft.Icons.PERSON, size=64)
        else:
            image_path = Paths.get_image_path() / file_key
            if not image_path.exists():
                Hub.download_file(f"images/{file_key}", Paths.get_image_path())
            image = Image(image_path, size=(IMAGE_SIZE, IMAGE_SIZE), fit=ft.BoxFit.COVER)
            image.on_tap = self._on_edit_image     # change it instead of opening it full screen
            self.image_slot.content = image
            self.page.run_task(broken_image_fallback, self.image_slot, image_path, lambda: self.image_slot.content is image)
        self.image_row.update()

    def _on_edit_image(self, e=None):
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text("Contact image"),
                actions=[
                    ft.TextButton("Upload image", on_click=self._on_upload_image, style=STYLES["button"]["style"]),
                    ft.TextButton("Choose from gallery", on_click=self._on_choose_from_gallery, style=STYLES["button"]["style"]),
                    ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog(), style=STYLES["button"]["style"]),
                ],
            )
        )

    async def _on_upload_image(self, e=None):
        self.page.pop_dialog()
        data = await self._pick_image_bytes()
        if data:
            await self._set_image(Hub.upload_contact_image, data)

    async def _pick_image_bytes(self) -> bytes | None:
        """android: the phone's photo picker, the bytes come with the result (there may be no file path).
        desktop: a file dialog for the types the hub accepts, the bytes are read from the path"""
        if self.page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
            files = await self.file_picker.pick_files(dialog_title="Contact image", file_type=ft.FilePickerFileType.IMAGE, with_data=True)
        else:
            files = await self.file_picker.pick_files(dialog_title="Contact image", file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=IMAGE_EXTENSIONS)
        if not files:
            return None
        if files[0].bytes:
            return files[0].bytes
        if files[0].path:
            return Path(files[0].path).read_bytes()
        logger.error("the picked image has neither bytes nor a path")
        return None

    def _on_choose_from_gallery(self, e=None):
        self.page.pop_dialog()

        def close(e=None):
            gallery.on_leave()
            self.page.pop_dialog()

        def select(file_key: str):
            close()
            self.page.run_task(self._set_image, Hub.pick_contact_image, file_key)

        gallery = GalleryPage(None, on_select=select)
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text("Choose from gallery"),
                content=ft.Container(width=500, height=600, content=gallery),
                actions=[ft.TextButton("Cancel", on_click=close, style=STYLES["button"]["style"])],
                on_dismiss=lambda e: gallery.on_leave(),
            )
        )
        gallery.on_enter()

    async def _set_image(self, send, value):
        """send: Hub.upload_contact_image (bytes) or Hub.pick_contact_image (file key), both answer the new file key"""
        file_key = await asyncio.to_thread(send, self.contact_id, value)
        if not file_key:
            self.page.show_dialog(ft.SnackBar(ft.Text("The image could not be set")))
            return
        self._show_image(file_key)

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
        data = self.get_data()
        _set_nested_value(data["profile"], ["tts_parameters", "voice_id"], self._resolve_voice_id())
        Hub.update_contact(self.contact_id, data)

        enabled = bool(self.companion_switch.value)
        if enabled != self.companion_loaded:
            if not Hub.set_contact_companion(self.contact_id, enabled):
                self.page.show_dialog(ft.SnackBar(ft.Text("The companion could not be switched " + ("on" if enabled else "off"))))
                return
            self.companion_loaded = enabled
        self.navigator("contacts")

    def _resolve_voice_id(self) -> str:
        # "" means the default voice. if the hub call fails keep the voice the contact had instead of wiping it
        if self.voice_selector.get_voice() is None:
            return ""
        voice_id = self.voice_selector.store_on_hub(self.gender_group.value or "")
        if not voice_id:
            logger.error("storing the voice failed, keeping the current voice")
            return self.voice_selector.current_voice_id
        return voice_id

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
        profile = copy.deepcopy(self.profile_base)
        profile.pop("companion", None)
        for path, kind, field in self.profile_fields:
            text = field.value or ""
            if kind == "list":
                _set_nested_value(profile, path, [line.strip() for line in text.splitlines() if line.strip()])
            elif kind == "long":
                _set_nested_value(profile, path, int(text))
            elif kind == "float":
                _set_nested_value(profile, path, float(text))
            else:
                _set_nested_value(profile, path, text)
        return {
            "identity": {
                "name": self.name.value or "",
                "gender": gender,
                "role": self.role.value or "",
                "age": self.age.value or "",
                "personality": self.personality.value or "",
            },
            "profile": profile,
        }