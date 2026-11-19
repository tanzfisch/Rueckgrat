import flet as ft
from app.ui import theme
from app.utils import Contact, Hub, Paths, Capabilities, Backroom

# the app level views, in the order of the tools grid: (route, icon, label, the capabilities it needs to be offered)
TOOLS = [
    ("translate", ft.Icons.TRANSLATE, "translate", ()),     # typing works with the llm alone, its mic and speech hide on their own
    ("contacts", ft.Icons.CHAT, "characters", ()),
    ("image", ft.Icons.IMAGE, "image generation", ("image",)),
    ("gallery", ft.Icons.PHOTO_LIBRARY, "gallery", ()),
    ("transcribe", ft.Icons.TRANSCRIBE, "transcribe", ()),   # the saved transcripts work without stt, its record button shows it
    ("backroom", ft.Icons.DOOR_BACK_DOOR, "Backroom", ()),    # #215 the agent jobs, passes and #170 tasks of all contacts
]
BACKROOM = "backroom"   # its tile and the tools button show how many jobs and passes run (Backroom.running_count)


class Header(ft.Row):
    def __init__(
        self,
        navigator,
        selected_contact: bool = True,
        back_button: bool = True,
        on_go_back=None,
        on_open_profile=None,
        actions: list | None = None,
        **kwargs,
    ):
        """actions: the page's own buttons, right aligned in front of the app tools and the menu"""
        self.navigator = navigator
        self.on_go_back = on_go_back
        self.on_open_profile = on_open_profile
        self.contact = None

        self.back_btn = ft.IconButton(
            icon=ft.Image(
                src=theme.icon("back"),
                width=24,
                height=24,
                fit=ft.BoxFit.CONTAIN,
            ),
            width=40,
            height=40,
            on_click=self.handle_go_back,
            style=theme.STYLES["icon_button"]["style"],
        )

        self.profile_label = ft.Image(
            src=theme.icon("profile"),
            width=40,
            height=40,
            fit=ft.BoxFit.COVER,
        )

        self.contact_name = ft.Text("...")

        self.menu_btn = ft.IconButton(
            icon=ft.Image(
                src=theme.icon("menu"),
                width=24,
                height=24,
                fit=ft.BoxFit.CONTAIN,
            ),
            width=40,
            height=40,
            on_click=self.handle_open_menu,
            style=theme.STYLES["icon_button"]["style"],
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
        controls.extend(actions or [])

        self._tools_btn = None
        if Hub.access_token:
            self._tools_btn = self._tools_menu()
            controls.append(self._tools_btn)
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
            style=theme.STYLES["icon_button"]["style"],
            on_click=self._open_tools,
            badge=self._running_badge(),
        )

    @staticmethod
    def _running_badge() -> ft.Badge | None:
        """#215 the number of running jobs and passes, None while none runs"""
        running = Backroom.running_count()
        return ft.Badge(label=str(running), bgcolor=theme.ACCENT, text_color=theme.ON_ACCENT) if running else None

    def did_mount(self):
        if self._tools_btn is not None:
            Backroom.add_listener(self._on_jobs)

    def will_unmount(self):
        Backroom.remove_listener(self._on_jobs)

    def _on_jobs(self, job_id=None):
        """Backroom changed: the running count on the tools button"""
        badge = self._running_badge()
        if (badge and badge.label) == (self._tools_btn.badge and self._tools_btn.badge.label):
            return
        self._tools_btn.badge = badge
        try:
            self._tools_btn.update()
        except RuntimeError:
            Backroom.remove_listener(self._on_jobs)     # not on the page any more

    def _open_tools(self, e):
        """the app level views as a grid of tiles (icon + label), a tap switches to it"""
        page = self.page    # the header can be rebuilt while the dialog is open, keep the page
        def pick(route: str):
            page.pop_dialog()
            self.navigator(route)

        tiles = [
            ft.Container(
                bgcolor=theme.SURFACE_3,
                border_radius=theme.RADIUS,
                padding=8,
                ink=True,
                on_click=lambda e, r=route: pick(r),
                tooltip=label,
                content=ft.Column(
                    [ft.Icon(icon, size=32, badge=self._running_badge() if route == BACKROOM else None),
                     ft.Text(label, text_align=ft.TextAlign.CENTER, color=theme.TEXT)],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                    tight=True,
                ),
            )
            for route, icon, label, needs in TOOLS if Capabilities.has(*needs)
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