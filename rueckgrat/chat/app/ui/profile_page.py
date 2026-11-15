import copy
import json
import flet as ft
from app.ui import theme

from app.ui import BasePage
from app.ui.widgets import Header, VoiceSelector, ProfileImageSlot
from app.utils import Contact, Hub
from app.audio import Text_To_Speech
from app.common import (get_logger, Utils, IMAGE_STYLE_OPTIONS, IMAGE_STYLE_ICONS, CHATTINESS_OPTIONS, QUIET_HOUR_OPTIONS, PHOTO_OPTIONS,
                        put_companion_switch, pop_companion_switch)

logger = get_logger()

COMPANION_SECTION = "Companion"   # shown under the companion switch, only while it is on

PROFILE_SECTIONS = [
    (COMPANION_SECTION, [
        ("Chattiness (default balanced)", ["companion_settings", "chattiness"], "select"),
        ("Quiet from (default 22:00)", ["companion_settings", "quiet_from"], "select"),
        ("Quiet until (default 08:00, the same hour twice: never quiet)", ["companion_settings", "quiet_until"], "select"),
        ("Photos (default allowed)", ["companion_settings", "photos"], "select"),
    ]),
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
    ("companion_settings", "chattiness"): CHATTINESS_OPTIONS,
    ("companion_settings", "quiet_from"): QUIET_HOUR_OPTIONS,
    ("companion_settings", "quiet_until"): QUIET_HOUR_OPTIONS,
    ("companion_settings", "photos"): PHOTO_OPTIONS,
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


SELECT_MAX_VISIBLE = 8         # longer option lists (the 24 quiet hours) scroll in a menu of this many rows
SELECT_ROW_HEIGHT = 48


def _select_field(label: str, path: list[str]) -> ft.Dropdown:
    options = SELECT_OPTIONS[tuple(path)]
    return ft.Dropdown(
        label=label,
        menu_height=SELECT_MAX_VISIBLE * SELECT_ROW_HEIGHT if len(options) > SELECT_MAX_VISIBLE else None,
        options=[
            ft.DropdownOption(
                key=option,
                text=f"{option.replace('_', ' ')}: {description}" if description else option.replace('_', ' '),
                leading_icon=_option_image(SELECT_ICONS.get(tuple(path), {}).get(option)),
            )
            for option, description in options.items()
        ],
        expand=True,
        filled=True,
        fill_color=theme.SURFACE_FIELD,
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
        self.voice_selector = VoiceSelector(Hub.get_predefined_voices(), on_play_sample=Text_To_Speech.play_voice_sample)
        self.companion_switch = ft.Switch(label="Companion (plans its own day, may write first)", active_color=theme.ACCENT,
                                          on_change=lambda e: self._show_companion_settings())
        self.companion_loaded = False   # the hub's state, a different switch value is sent on save

        # original profile dict, so fields without a form entry survive a save
        self.profile_base = {}
        self.profile_fields = []  # (key path, kind, TextField)
        profile_controls, companion_controls = [], []
        for section, fields in PROFILE_SECTIONS:
            controls = companion_controls if section == COMPANION_SECTION else profile_controls
            controls.append(ft.Text(section, style=theme.STYLES["section_heading"]))
            for label, path, kind in fields:
                field = _select_field(label, path) if kind == "select" else _text_field(label, kind)
                self.profile_fields.append((path, kind, field))
                controls.append(field)
        self.companion_settings = ft.Column(controls=companion_controls, spacing=12, visible=False)
        self.file_picker = ft.FilePicker()

        # the contact's current profile image, a tap on it or on the pen changes it. hidden for a new contact
        self.profile_image = ProfileImageSlot(
            title="Contact image",
            on_upload=lambda data: Hub.upload_contact_image(self.contact_id, data),
            on_pick=lambda file_key: Hub.pick_contact_image(self.contact_id, file_key),
            visible=False,
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
                                self.profile_image,
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
                                self.companion_settings,
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
                                ft.Button("Load", width=float("inf"), on_click=self._on_load, style=theme.STYLES["button"]["style"]),
                                ft.Button("Export", width=float("inf"), on_click=self._on_export, style=theme.STYLES["button"]["style"]),
                                ft.Row(
                                    controls=[
                                        ft.Button("Cancel", expand=True, on_click=self._on_cancel, style=theme.STYLES["button"]["style"]),
                                        ft.Button("Save Profile", expand=True, on_click=self._on_save, style=theme.STYLES["button"]["style"]),
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
        self.navigator.back()

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
        self.profile_image.visible = False
        self.companion_switch.value = self.companion_loaded = False
        self.companion_settings.visible = False
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
        voice_id = Utils.get_nested_value(profile, ["tts_parameters", "voice_id"], "")
        # fetch again, the user may have stored more predefined voices since the selector was built
        self.voice_selector.set_current_voice(voice_id, Hub.get_predefined_voices() if voice_id else None)
        self.update()

    def load_profile(self):
        self.clear_form()
        if self.contact_id == -1:
            return
        contact = Hub.get_contact(self.contact_id)
        self.fill_form(contact)
        # only the hub sets the flag (PUT /contacts/{id}/companion), so it is read here and not in fill_form: _on_load only sets the switch
        self.companion_loaded = bool(Utils.get_nested_value(contact, ["profile", "companion"], False))
        self.companion_switch.value = self.companion_loaded
        self.companion_switch.update()
        self._show_companion_settings()
        self.profile_image.visible = True
        self.profile_image.show(Contact(contact or {}).get_latest_profile_image_name())

    def _show_companion_settings(self):
        """the companion settings only while the switch is on. hidden fields keep their values, they are saved either way"""
        self.companion_settings.visible = bool(self.companion_switch.value)
        self.companion_settings.update()

    async def _on_load(self, e=None):
        files = await self.file_picker.pick_files(dialog_title="Import Profile")
        if not files or not files[0].path:
            return
        with open(files[0].path, "r") as file:
            data = json.load(file)
        companion = pop_companion_switch(data)
        self.fill_form(data)
        # only the switch, Save sends a changed value through PUT /contacts/{id}/companion
        self.companion_switch.value = companion
        self.companion_switch.update()
        self._show_companion_settings()

    async def _on_export(self, e=None):
        path = await self.file_picker.save_file(dialog_title="Export Profile")
        if not path:
            return
        data = self.get_data()
        voice = self.voice_selector.get_voice()
        if voice and "predefined_id" in voice:
            # the voices.json id instead of the uuid, the uuid differs between hubs. the hub resolves it on import
            _set_nested_value(data["profile"], ["tts_parameters", "voice_id"], voice["predefined_id"])
        put_companion_switch(data, self.companion_switch.value)
        with open(path, "w") as file:
            json.dump(data, file, indent=4)

    def _on_cancel(self, e=None):
        self.navigator.back()

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
        self.navigator.back()

    def _resolve_voice_id(self) -> str:
        # "" means the default voice. if the hub call fails keep the voice the contact had instead of wiping it
        voice = self.voice_selector.get_voice()
        if voice is None:
            return ""
        if "voice_id" in voice:
            voice_id = voice["voice_id"]
        elif "predefined_id" in voice:
            voice_id = Hub.use_predefined_voice(voice["predefined_id"])
        else:
            voice_id = Hub.upload_voice(voice["bytes"], self.gender_group.value or "")
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