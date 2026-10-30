import flet as ft
from app.ui.theme import STYLES, SURFACE_3, TEXT_DIM

from app.ui import BasePage
from app.ui.widgets import RowSelector, Header, MessageBox
from app.utils import RueckgratConfig, Hub
from app.ui.profile_wizzard import ProfileWizzardMode

# common IANA zones, east to west. the hub accepts any IANA name, one not listed here is added when it is the stored one
TIMEZONES = [
    "Pacific/Auckland", "Australia/Sydney", "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Australia/Perth",
    "Asia/Kolkata", "Asia/Dubai", "Europe/Moscow", "Europe/Istanbul", "Africa/Johannesburg", "Europe/Berlin",
    "Europe/London", "UTC", "America/Sao_Paulo", "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
]


def _section(title: str, *controls) -> ft.Column:
    # same heading style as the sections of the contact profile page
    heading = ft.Text(title, style=STYLES["section_heading"])
    return ft.Column([heading, *controls], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


class NetworkSettingsPage(ft.Column):
    def __init__(self):
        # same layout as the profile tab: scrolls, fields and buttons share the width
        super().__init__(expand=True, spacing=28, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.on_ok = None
        self.config = RueckgratConfig()

        self.host_input = ft.TextField(label="Host", value=self.config.host, **STYLES["field"])
        self.port_input = ft.TextField(label="Port", value=self.config.port, **STYLES["field"])

        self.controls = [
            _section(
                "Hub connection",
                ft.Text("host name or IP address and port of your Rueckgrat hub", color=TEXT_DIM, size=12),
                self.host_input,
                self.port_input,
                ft.Button("Save", on_click=self._ok, style=STYLES["button"]["style"]),
            ),
        ]

    def _ok(self, e=None):
        self.config.host = self.host_input.value or ""
        self.config.port = self.port_input.value or ""
        if self.on_ok:
            self.on_ok()


class ProfileSettingsPage(ft.Column):
    """who the user is to the contacts: name, look and backstory"""
    def __init__(self, navigator):
        # scrolls, so small screens can reach every section. STRETCH gives fields and buttons the same width
        super().__init__(expand=True, spacing=28, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.navigator = navigator
        self.controls = [
            _section(
                "Profile",
                *self._profile_summary(),
                ft.Button("edit profile", on_click=self.on_click_user_profile, style=STYLES["button"]["style"]),
            ),
        ]

    @staticmethod
    def _profile_summary() -> list:
        # text only. the page is built on every visit, so this is always the stored profile
        profile = (Hub.get_user_data() or {}).get("profile") or {}
        name = (profile.get("name") or "").strip()
        hair, eyes = profile.get("hair_color"), profile.get("eye_color")
        attributes = [profile.get("gender"), profile.get("age"), hair and f"{hair} hair", eyes and f"{eyes} eyes", profile.get("ethnicity"), profile.get("body_type")]
        attributes = ", ".join(str(a) for a in attributes if a)
        backstory = (profile.get("backstory") or "").strip()

        texts = []
        if name:
            texts.append(ft.Text(name, weight=ft.FontWeight.BOLD))
        if attributes:
            texts.append(ft.Text(attributes))
        if backstory:
            texts.append(ft.Text(backstory, color=TEXT_DIM, size=12, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS))
        return texts or [ft.Text("no profile yet", color=TEXT_DIM, size=12)]


    def on_click_user_profile(self, e=None):
        self.navigator("profile_wizz", user_profile_mode=ProfileWizzardMode.UserChange)


class AccountSettingsPage(ft.Column):
    """login and the details the hub keeps: email, password, logout"""
    def __init__(self, navigator):
        # scrolls, so small screens can reach every section. STRETCH gives fields and buttons the same width
        super().__init__(expand=True, spacing=28, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.navigator = navigator
        # optional, the hub only checks the format
        self.email_edit = ft.TextField(label="Email (optional)", value=Hub.get_email(), **STYLES["field"])
        self.current_pass_edit = ft.TextField(label="Current password", password=True, can_reveal_password=True, **STYLES["field"])
        self.new_pass_edit = ft.TextField(label="New password", password=True, can_reveal_password=True, **STYLES["field"])
        self.confirm_pass_edit = ft.TextField(label="Confirm new password", password=True, can_reveal_password=True, **STYLES["field"])
        self.controls = [
            _section(
                "User name",
                ft.Text(Hub.get_user_name() or "unknown", weight=ft.FontWeight.BOLD),   # the login name, can't be changed
            ),
            _section(
                "Email",
                self.email_edit,
                ft.Button("save email", on_click=self.on_click_save_email, style=STYLES["button"]["style"]),
            ),
            _section(
                "Password",
                self.current_pass_edit,
                self.new_pass_edit,
                self.confirm_pass_edit,
                ft.Button("change password", on_click=self.on_click_change_password, style=STYLES["button"]["style"]),
            ),
            # the session action, kept apart from the account settings
            ft.Column([
                ft.Divider(color=SURFACE_3),
                ft.Button("logout", on_click=self.on_click_logout, style=STYLES["button"]["style"]),
            ], spacing=20, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        ]

    def on_click_save_email(self, e=None):
        error = Hub.set_email(self.email_edit.value or "")
        if error:
            MessageBox.error(self.page, error, title="Email not saved")
            return
        MessageBox.show(self.page, "your email has been saved", title="Email saved")

    def on_click_change_password(self, e=None):
        if self.new_pass_edit.value != self.confirm_pass_edit.value:
            MessageBox.error(self.page, "the new passwords do not match", title="Password not changed")
            return
        error = Hub.change_password(self.current_pass_edit.value or "", self.new_pass_edit.value or "")
        if error:
            MessageBox.error(self.page, error, title="Password not changed")
            return
        for edit in (self.current_pass_edit, self.new_pass_edit, self.confirm_pass_edit):
            edit.value = ""
        self.update()
        MessageBox.show(self.page, "your password has been changed", title="Password changed")

    def on_click_logout(self, e=None):
        self.page.run_task(self._logout)

    async def _logout(self):
        await Hub.logout()
        self.navigator("login")


class PreferencesSettingsPage(ft.Column):
    """how the app behaves for the user: timezone (on the hub), chat input (this device)"""
    def __init__(self, navigator):
        # scrolls, so small screens can reach every section. STRETCH gives fields and buttons the same width
        super().__init__(expand=True, spacing=28, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.navigator = navigator
        # the companions of all contacts plan their day and keep quiet hours in it
        timezone = Hub.get_timezone()   # "" if the hub can't be reached, then nothing is selected
        timezones = TIMEZONES if timezone in TIMEZONES or not timezone else [timezone, *TIMEZONES]
        self.timezone_edit = ft.Dropdown(label="Timezone", value=timezone or None,
                                         options=[ft.DropdownOption(key=tz, text=tz) for tz in timezones], **STYLES["field"])
        # stored on this device only, saved on change
        self.enter_sends_switch = ft.Switch(value=RueckgratConfig().enter_sends, on_change=self.on_enter_sends_changed)
        self.controls = [
            _section(
                "Timezone",
                self.timezone_edit,
                ft.Button("save timezone", on_click=self.on_click_save_timezone, style=STYLES["button"]["style"]),
            ),
            _section(
                "Chat",
                ft.Text("when off, ctrl+enter sends", color=TEXT_DIM, size=12),
                # a switch label doesn't wrap, a Text next to it does
                ft.Row([self.enter_sends_switch, ft.Text("Enter sends the message (shift+enter for a new line)", expand=True)]),
            ),
        ]

    def on_click_save_timezone(self, e=None):
        if not self.timezone_edit.value:
            MessageBox.error(self.page, "please choose a timezone", title="Timezone not saved")
            return
        error = Hub.set_timezone(self.timezone_edit.value)
        if error:
            MessageBox.error(self.page, error, title="Timezone not saved")
            return
        MessageBox.show(self.page, "your timezone has been saved", title="Timezone saved")

    def on_enter_sends_changed(self, e=None):
        RueckgratConfig().enter_sends = self.enter_sends_switch.value


class SettingsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.header = Header(navigator, False, True)
        self.header.on_go_back = self.on_go_back

        logged_in = bool(Hub.access_token)
        # before login only the hub connection can be set
        self.pages = {"Network": NetworkSettingsPage()}
        if logged_in:
            self.pages = {
                "Profile": ProfileSettingsPage(self.navigator),
                "Account": AccountSettingsPage(self.navigator),
                "Preferences": PreferencesSettingsPage(self.navigator),
                **self.pages,
            }
        else:
            self.pages["Network"].on_ok = self.on_go_back
        tabs = list(self.pages)
        self.content_slot = ft.Container(content=self.pages[tabs[0]], expand=True)

        self.page_selector = RowSelector(tabs, True, 1)
        self.page_selector.on_selection_changed = self.on_page_changed
        self.page_selector.select(tabs[0])

        self.controls = [
            ft.Container(
                padding=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.header,
                        ft.Row(
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                            controls=[
                                ft.Container(
                                    width=120,   # fits "Preferences"
                                    content=ft.Column(
                                        controls=[
                                            self.page_selector,
                                            ft.Container(expand=True),
                                        ]
                                    ),
                                ),
                                self.content_slot,
                            ],
                        ),
                    ],
                ),
            )
        ]

    def on_go_back(self, e=None):
        if not self.navigator.back():
            self.navigator("contacts" if Hub.access_token else "login")

    def on_page_changed(self, page_name: str):
        self.content_slot.content = self.pages[page_name]
        self.content_slot.update() 