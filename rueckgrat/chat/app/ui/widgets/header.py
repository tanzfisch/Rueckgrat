import os
import flet as ft
from app.ui.theme import STYLES
from app.utils import Contact, Hub, Paths

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"

def _tool_icon(icon, tooltip: str) -> ft.Control:
    """icon only menu entry, the tooltip names it"""
    if isinstance(icon, str):
        return ft.Image(src=icon, width=24, height=24, fit=ft.BoxFit.CONTAIN, tooltip=tooltip)
    return ft.Icon(icon, tooltip=tooltip)


class Header(ft.Row):
    def __init__(
        self,
        navigator,
        selected_contact: bool = True,
        back_button: bool = True,
        on_go_back=None,
        on_open_profile=None,
        **kwargs,
    ):
        self.navigator = navigator
        self.on_go_back = on_go_back
        self.on_open_profile = on_open_profile
        self.contact = None

        self.back_btn = ft.IconButton(
            icon=ft.Image(
                src=f"{ASSETS_DIR}/icons/back_light.png",
                width=24,
                height=24,
                fit=ft.BoxFit.CONTAIN,
            ),
            width=40,
            height=40,
            on_click=self.handle_go_back,
            style=STYLES["icon_button"]["style"],
        )

        self.profile_label = ft.Image(
            src=f"{ASSETS_DIR}/icons/profile_light.png",
            width=40,
            height=40,
            fit=ft.BoxFit.COVER,
        )

        self.contact_name = ft.Text("...")

        self.menu_btn = ft.IconButton(
            icon=ft.Image(
                src=f"{ASSETS_DIR}/icons/menu_light.png",
                width=24,
                height=24,
                fit=ft.BoxFit.CONTAIN,
            ),
            width=40,
            height=40,
            on_click=self.handle_open_menu,
            style=STYLES["icon_button"]["style"],
        )

        controls = []
        if back_button:
            controls.append(self.back_btn)
        if selected_contact:
            controls.append(
                ft.GestureDetector(
                    content=ft.Row(
                        [self.profile_label, self.contact_name],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    on_tap=self._open_profile,
                )
            )
        controls.append(ft.Container(expand=True))
        # app level tools, only with a logged in session (not on the login page)
        if Hub.access_token:
            controls.append(self._tools_menu())
        controls.append(self.menu_btn)

        super().__init__(
            controls=controls,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            **kwargs,
        )

    def _tools_menu(self) -> ft.PopupMenuButton:
        return ft.PopupMenuButton(
            icon=ft.Icons.APPS,
            tooltip="tools",
            style=STYLES["icon_button"]["style"],
            items=[
                ft.PopupMenuItem(content=_tool_icon(ft.Icons.TRANSLATE, "translate"), on_click=lambda e: self.navigator("translate")),
                ft.PopupMenuItem(content=_tool_icon(ft.Icons.CHAT, "chat"), on_click=lambda e: self.navigator("contacts")),
                ft.PopupMenuItem(content=_tool_icon(ft.Icons.IMAGE, "image generation"), on_click=lambda e: self.navigator("image")),
            ],
        )

    def set_contact(self, contact: Contact):
        self.contact = contact
        self.contact_name.value = self.contact.get_name()
        name = self.contact.get_latest_profile_image_name()
        if name:
            self.profile_label.src = Paths.image_src(Paths.get_image_path() / name, self.page.web)
        if self.page:
            self.update()

    def _open_profile(self, e):
        if self.on_open_profile:
            self.on_open_profile()

    def handle_go_back(self, e):
        if self.on_go_back:
            self.on_go_back()

    def handle_open_menu(self, e):
        self.navigator("settings")