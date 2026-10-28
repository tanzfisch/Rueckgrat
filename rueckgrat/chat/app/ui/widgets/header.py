import os
import flet as ft
from app.ui.theme import STYLES, RADIUS, SURFACE_3, TEXT
from app.utils import Contact, Hub, Paths

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"

# the app level views, in the order of the tools grid: (route, icon, label)
TOOLS = [
    ("translate", ft.Icons.TRANSLATE, "translate"),
    ("contacts", ft.Icons.CHAT, "charaters"),
    ("image", ft.Icons.IMAGE, "image generation"),
    ("gallery", ft.Icons.PHOTO_LIBRARY, "gallery"),
]


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

    def _tools_menu(self) -> ft.IconButton:
        return ft.IconButton(
            icon=ft.Icons.APPS,
            tooltip="tools",
            width=40,
            height=40,
            style=STYLES["icon_button"]["style"],
            on_click=self._open_tools,
        )

    def _open_tools(self, e):
        """the app level views as a grid of tiles (icon + label), a tap switches to it"""
        def pick(route: str):
            self.page.pop_dialog()
            self.navigator(route)

        tiles = [
            ft.Container(
                bgcolor=SURFACE_3,
                border_radius=RADIUS,
                padding=8,
                ink=True,
                on_click=lambda e, r=route: pick(r),
                content=ft.Column(
                    [ft.Icon(icon, size=32), ft.Text(label, text_align=ft.TextAlign.CENTER, color=TEXT)],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                    tight=True,
                ),
            )
            for route, icon, label in TOOLS
        ]
        tile, gap, columns = 120, 10, 2      # square tiles, the dialog is as high as its rows
        rows = (len(tiles) + columns - 1) // columns
        self.page.show_dialog(ft.AlertDialog(
            modal=False,
            content_padding=ft.Padding.all(15),
            actions_padding=ft.Padding.all(0),
            content=ft.Container(
                width=columns * tile + (columns - 1) * gap,
                height=rows * tile + (rows - 1) * gap,
                content=ft.GridView(controls=tiles, runs_count=columns, child_aspect_ratio=1.0, spacing=gap, run_spacing=gap),
            ),
        ))

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