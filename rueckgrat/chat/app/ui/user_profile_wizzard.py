import json
import flet as ft
from app.ui import theme

from app.utils import Hub
from app.ui.wizzard_base import WizardPage, wizard_row, ASSETS_DIR
from app.ui.widgets import RowSelector, MessageBox
from app.ui.settings_page import timezone_options


class UserProfileForm(ft.Column):
    """the user's own character: name, gender, age, hair, eyes, ethnicity, body type and backstory"""

    # icon names, theme.icon() picks the light or dark drawing when the page is built
    _male_age_icons = {
        "18": "male_teen",
        "22": "male_20s",
        "27": "male_30s",
        "45": "male_40s",
        "60": "male_old",
    }

    _female_age_icons = {
        "18": "female_teen",
        "22": "female_20s",
        "27": "female_30s",
        "45": "female_40s",
        "60": "female_old",
    }

    hair_color = {
        "black": f"{ASSETS_DIR}/icons/hair_black.png",
        "dark brown": f"{ASSETS_DIR}/icons/hair_dark_brown.png",
        "brown": f"{ASSETS_DIR}/icons/hair_brown.png",
        "bright brown": f"{ASSETS_DIR}/icons/hair_bright_brown.png",
        "blonde": f"{ASSETS_DIR}/icons/hair_blonde.png",
        "red": f"{ASSETS_DIR}/icons/hair_red.png",
        "gray": f"{ASSETS_DIR}/icons/hair_gray.png",
    }

    eye_color = {
        "black": f"{ASSETS_DIR}/icons/eye_black.png",
        "dark brown": f"{ASSETS_DIR}/icons/eye_dark_brown.png",
        "bright brown": f"{ASSETS_DIR}/icons/eye_bright_brown.png",
        "green": f"{ASSETS_DIR}/icons/eye_green.png",
        "blue": f"{ASSETS_DIR}/icons/eye_blue.png",
        "gray": f"{ASSETS_DIR}/icons/eye_gray.png",
        "red": f"{ASSETS_DIR}/icons/eye_red.png",
    }

    ethnicity_options = {
        "East Asian": "",
        "South Asian": "",
        "Southeast Asian": "",
        "Middle Eastern": "",
        "African": "",
        "European": "",
        "Latino": "",
        "Native American": "",
        "Oceanian": "",
    }

    _body_type_icons = {
        "underweight": "body_underweight",
        "athletic": "body_normal",
        "curvy": "body_overweight",
        "overweight": "body_obese",
        "obese": "body_morbidly_obese",
    }

    def __init__(self, profile: dict = None):
        super().__init__(expand=True, spacing=14, scroll=ft.ScrollMode.AUTO)
        self.male_ages = {k: theme.icon(v) for k, v in self._male_age_icons.items()}
        self.female_ages = {k: theme.icon(v) for k, v in self._female_age_icons.items()}
        self.body_type = {k: theme.icon(v) for k, v in self._body_type_icons.items()}

        self.name_input = ft.TextField(
            value=((profile or {}).get("name") or "").strip(),
            hint_text="Name of your character",
            on_change=self.on_name_changed,
            filled=True,
            bgcolor=theme.SURFACE_FIELD,
            border=theme.field_border(22, theme.ACCENT),
            content_padding=ft.Padding.only(left=16, right=16, top=10, bottom=10),
            height=44,
        )

        self.gender = RowSelector({"male": theme.icon("male"), "female": theme.icon("female")})
        self.gender.on_selection_changed = self.on_gender_changed
        self.gender.select(profile["gender"] if profile else "male")

        self.age = RowSelector(self.male_ages)
        if profile:
            ages = [int(k) for k in self.male_ages]
            closest = min(ages, key=lambda x: abs(x - profile["age"]))
            self.age.select(str(closest))
        else:
            self.age.select("22")

        self.hair = RowSelector(self.hair_color, True, 7)
        self.hair.select(profile["hair_color"]) if profile else self.hair.select_random()

        self.eye = RowSelector(self.eye_color, True, 7)
        self.eye.select(profile["eye_color"]) if profile else self.eye.select_random()

        self.ethnicity = RowSelector(self.ethnicity_options, False, 3)
        self.ethnicity.select(profile["ethnicity"]) if profile else self.ethnicity.select_random()

        self.body = RowSelector(self.body_type, True, 5)
        self.body.select(profile["body_type"]) if profile else self.body.select_random()

        self.backstory = ft.TextField(
            hint_text="Type optional backstory here ...",
            multiline=True,
            min_lines=4,
            max_lines=8,
            value=profile["backstory"] if profile else "",
            filled=True,
            bgcolor=theme.SURFACE_FIELD,
            border=theme.field_border(16, theme.ACCENT),
            content_padding=16,
        )

        self.controls = [
            wizard_row("Name", self.name_input),
            wizard_row("Gender", self.gender),
            wizard_row("Age", self.age),
            wizard_row("Hair", self.hair),
            wizard_row("Eyes", self.eye),
            wizard_row("Ethnicity", self.ethnicity),
            wizard_row("Body Type", self.body),
            wizard_row("Backstory", self.backstory),
        ]

    def on_name_changed(self, e=None):
        # clear the validation message once the user starts typing
        if self.name_input.error:
            self.name_input.error = None
            self.name_input.update()

    def validate_name(self) -> bool:
        if (self.name_input.value or "").strip():
            return True
        self.name_input.error = "Please enter a name for your character"
        self.name_input.update()
        return False

    def on_gender_changed(self, gender: str):
        self.age.update_images(self.male_ages if gender == "male" else self.female_ages)

    def get_values(self):
        return {
            "name": (self.name_input.value or "").strip(),
            "gender": self.gender.get_selected(),
            "age": int(self.age.get_selected()),
            "hair_color": self.hair.get_selected(),
            "eye_color": self.eye.get_selected(),
            "ethnicity": self.ethnicity.get_selected(),
            "body_type": self.body.get_selected(),
            "backstory": self.backstory.value or "",
        }


class WhereForm(ft.Column):
    """time zone (the companions plan their day in it) and the optional email, both kept on the hub"""

    def __init__(self):
        super().__init__(expand=True, spacing=14, scroll=ft.ScrollMode.AUTO)
        timezone = Hub.get_timezone()   # the hub answers its default if none is set, "" if it can't be reached
        self.timezone = ft.Dropdown(
            value=timezone or None,
            options=timezone_options(timezone),
            expand=True,
            filled=True,
            fill_color=theme.SURFACE_FIELD,
            menu_height=400,
        )
        self.email_input = ft.TextField(
            value=Hub.get_email(),
            hint_text="optional",
            on_change=self.on_email_changed,
            filled=True,
            bgcolor=theme.SURFACE_FIELD,
            border=theme.field_border(22, theme.ACCENT),
            content_padding=ft.Padding.only(left=16, right=16, top=10, bottom=10),
            height=44,
        )
        self.controls = [
            wizard_row("Time zone", self.timezone),
            wizard_row("Email", self.email_input),
        ]

    def on_email_changed(self, e=None):
        if self.email_input.error:
            self.email_input.error = None
            self.email_input.update()

    def validate_email(self) -> bool:
        # only a light check, the hub checks the format again. empty is fine, the email is optional
        email = (self.email_input.value or "").strip()
        if not email or ("@" in email and "." in email.rsplit("@", 1)[1]):
            return True
        self.email_input.error = "Please enter a valid email or leave it empty"
        self.email_input.update()
        return False


class UserProfileWizard(WizardPage):
    """the user's own profile. first_setup=True right after the first login: time zone and email first, then the profile"""

    show_cancel = True

    def __init__(self, navigator):
        super().__init__(navigator)
        self.first_setup = False
        self.where = None

    def _leave(self):
        if self.first_setup or not self.navigator.back():
            self.navigator("contacts")

    def _on_where_page(self) -> bool:
        return self.where is not None and self.content_slot.content is self.where

    def on_go_back(self, e=None):
        # the header's back: from the profile back to the time zone page, otherwise out
        if self.first_setup and not self._on_where_page():
            self._show_where()
            return
        self._leave()

    def on_cancel(self, e=None):
        # Skip on the time zone page goes on to the profile without saving, Skip or Cancel on the profile leaves
        if self._on_where_page():
            self._show_profile()
            return
        self._leave()

    def on_submit(self, e=None):
        if self._on_where_page():
            self._save_where()
            return
        if not self.form.validate_name():
            return
        Hub.update_user_data({"profile": json.dumps(self.form.get_values())})
        self._leave()

    def _save_where(self):
        if not self.where.validate_email():
            return
        email = (self.where.email_input.value or "").strip()
        error = Hub.set_timezone(self.where.timezone.value) if self.where.timezone.value else None
        if not error and email:
            error = Hub.set_email(email)
        if error:
            MessageBox.error(self.page, error, title="Not saved")
            return
        self._show_profile()

    def _show_where(self):
        self.cancel_btn.content = "Skip"
        self._show(self.where, "Next", "Profile Settings", "")

    def _show_profile(self):
        self.cancel_btn.content = "Skip" if self.first_setup else "Cancel"
        self._show(self.form, "Save", "About you", "Your own role play or real character as it will be described to the AI")

    def on_enter(self, **kwargs):
        self.first_setup = kwargs.get("first_setup", False)
        data = Hub.get_user_data()
        self.form = UserProfileForm(profile=data["profile"] if data and "profile" in data else None)
        if self.first_setup:
            self.where = WhereForm()
            self._show_where()
        else:
            self._show_profile()
