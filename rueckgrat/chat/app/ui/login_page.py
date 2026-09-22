import flet as ft

from app.ui import BasePage
from app.ui.widgets import OneLineBubble
from app.utils import Hub
from app.common import get_logger
from app.ui.theme import STYLES

logger = get_logger()


class UserSelectionPage(ft.Column):
    def __init__(self, users, user_chosen, goto_create):
        super().__init__(expand=True, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        items = []
        for user in users:
            bubble = OneLineBubble(user["username"], user["id"])
            bubble.on_click = lambda e, u=user["username"], i=user["id"]: user_chosen(u, i)
            items.append(bubble)

        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                    controls=items,
                ),
            ),
            ft.Container(
                padding=10,
                margin=10,
                content=ft.Button(
                    "Add User",
                    on_click=lambda e: goto_create(),
                    **STYLES["button"],
                ),
            )
        ]


class PasswordPage(ft.Container):
    def __init__(self, goto_select, check_login):
        self.user_bubble = OneLineBubble()
        self.password_edit = ft.TextField(
            password=True,
            can_reveal_password=True,
            text_align=ft.TextAlign.CENTER,
            autofocus=True,
            on_submit=lambda e: check_login(),
            **STYLES["field"],
        )
        super().__init__(
            expand=True,
            margin=20,
            content=ft.Column(
                expand=True,
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Container(expand=True),
                    self.user_bubble,
                    self.password_edit,
                    ft.Container(expand=True),
                    ft.Row(
                        controls=[
                            ft.Button("Change User", expand=True, on_click=lambda e: goto_select(), **STYLES["button"]),
                            ft.Button("Login", expand=True, on_click=lambda e: check_login(), **STYLES["button"]),
                        ]
                    ),
                ],
            ),
        )

class AddUserPage(ft.Column):
    def __init__(self, create_user, goto_select, horizontal_alignment=ft.CrossAxisAlignment.STRETCH):
        super().__init__(expand=True, spacing=8)
        self.name_edit = ft.TextField(label="Name", expand=True, **STYLES["field"])
        self.pass_edit = ft.TextField(label="Password", password=True, can_reveal_password=True, expand=True, **STYLES["field"])

        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        self.name_edit,
                        self.pass_edit
                    ]
                )
            ),
            ft.Container(
                padding=10,
                margin=10,
                content=ft.Row(
                    controls=[
                        ft.Button("Cancel", expand=True, on_click=lambda e: goto_select(), **STYLES["button"]),
                        ft.Button("Create", expand=True, on_click=lambda e: create_user(), **STYLES["button"]),
                    ]
                ),                
            )
        ]


class LoginPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.expand = True
        self.spacing = 0
        self.users = Hub.get_users()
        self.selected_user = None
        self.user_name = None

        self.user_page = UserSelectionPage(self.users, self.user_chosen, self.goto_create_user)
        self.pass_page = PasswordPage(self.goto_select_user, self.check_login)
        self.add_page = AddUserPage(self.create_user, self.goto_select_user)

        if not self.users:
            start = self.add_page
        elif len(self.users) == 1:
            start = self.pass_page
            u = self.users[0]
            self.user_name = u["username"]
            self.pass_page.user_bubble.set(u["username"], u["id"])
        else:
            start = self.user_page

        self.controls = [start]

    def _show(self, widget):
        self.controls = [widget]
        self.update()

    def goto_create_user(self):
        self._show(self.add_page)

    def goto_select_user(self):
        self.pass_page.password_edit.value = ""
        self._show(self.user_page)

    def user_chosen(self, name, uid):
        self.user_name = name
        self.pass_page.user_bubble.set(name, uid)
        self._show(self.pass_page)

    def create_user(self):
        name = self.add_page.name_edit.value or ""
        pwd = self.add_page.pass_edit.value or ""
        Hub.create_user(name, pwd)
        if Hub.login_user(name, pwd):
            self.on_successful_login()
        else:
            logger.error("login failed")

    def check_login(self):
        pwd = self.pass_page.password_edit.value or ""
        if Hub.login_user(self.user_name, pwd):
            self.on_successful_login()
        else:
            logger.error("login failed")

    def on_successful_login(self):
        if not Hub.get_user_data():
            self.navigator("profile_wizz", user_profile_mode=True)
        else:
            self.navigator("contacts")