import flet as ft
from app.ui.theme import STYLES, SURFACE_3, TEXT_DIM

from app.ui import BasePage
from app.ui.widgets import RowSelector, ContactHeader, MessageBox
from app.utils import RueckgratConfig, Hub


def _section(title: str, *controls) -> ft.Column:
    # same heading style as the sections of the contact profile page
    heading = ft.Text(title, weight=ft.FontWeight.BOLD, size=16)
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


class UserProfileSettingsPage(ft.Column):
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
                "Profile",
                *self._profile_summary(),
                ft.Button("edit profile", on_click=self.on_click_user_profile, style=STYLES["button"]["style"]),
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
        self.navigator("profile_wizz", user_profile_mode=True)

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


class SettingsPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.contact_header = ContactHeader(navigator, False, True)
        self.contact_header.on_go_back = self.on_go_back

        self.profile_page = UserProfileSettingsPage(self.navigator)
        self.network_page = NetworkSettingsPage()
        self.content_slot = ft.Container(content=self.profile_page, expand=True)

        self.page_selector = RowSelector(["Profile", "Network"], True, 1)
        self.page_selector.on_selection_changed = self.on_page_changed
        self.page_selector.select("Profile")

        self.controls = [
            ft.Container(
                padding=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.contact_header,
                        ft.Row(
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                            controls=[
                                ft.Container(
                                    width=100,
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
        self.navigator("contacts")

    def on_page_changed(self, page_name: str):
        pages = {"Profile": self.profile_page, "Network": self.network_page}
        self.content_slot.content = pages[page_name]
        self.content_slot.update() 