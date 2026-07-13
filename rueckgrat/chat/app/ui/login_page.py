from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QStackedLayout,
    QWidget, QScrollArea, QLineEdit, QFormLayout,
    QPushButton, QLabel
)
from PySide6.QtCore import Qt

from app.ui import BasePage
from app.ui.widgets import OneLineBubble
from app.utils import Hub

from app.common import get_logger
logger = get_logger()


class VCenterLabel(QWidget):
    def __init__(self, text):
        super().__init__()
        self.setObjectName("login")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel(text))


class UserSelectionPage(QWidget):
    def __init__(self, users, user_chosen, goto_create):
        super().__init__()
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.list_layout = QVBoxLayout(content)
        self.list_layout.addStretch()

        for user in users:
            bubble = OneLineBubble(user["username"], user["id"])
            bubble.clicked.connect(lambda u=user["username"], i=user["id"]: user_chosen(u, i))
            self.list_layout.addWidget(bubble)
        self.list_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        btn = QPushButton("Add User")
        btn.clicked.connect(goto_create)
        layout.addWidget(btn)


class PasswordPage(QWidget):
    def __init__(self, goto_select, check_login):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addStretch()

        self.user_bubble = OneLineBubble()
        self.user_bubble.setFixedHeight(40)
        layout.addWidget(self.user_bubble)

        self.password_edit = QLineEdit()
        self.password_edit.setObjectName("login")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setAlignment(Qt.AlignCenter)
        self.password_edit.returnPressed.connect(check_login)
        layout.addWidget(self.password_edit)

        btns = QWidget()
        btn_layout = QHBoxLayout(btns)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        change_btn = QPushButton("Change User")
        change_btn.clicked.connect(goto_select)
        btn_layout.addWidget(change_btn)

        login_btn = QPushButton("Login")
        login_btn.clicked.connect(check_login)
        btn_layout.addWidget(login_btn)

        layout.addStretch()
        layout.addWidget(btns)


class AddUserPage(QWidget):
    def __init__(self, create_user, goto_select):
        super().__init__()
        layout = QVBoxLayout(self)

        layout.addStretch()

        form_container = QWidget()
        self.form = QFormLayout(form_container)
        self.form.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("login")
        self.form.addRow(VCenterLabel("Name"), self.name_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setObjectName("login")
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.form.addRow(VCenterLabel("Password"), self.pass_edit)

        layout.addWidget(form_container)
        layout.addStretch()

        btns = QWidget()
        btn_layout = QHBoxLayout(btns)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(goto_select)
        btn_layout.addWidget(cancel)

        create = QPushButton("Create")
        create.clicked.connect(create_user)
        btn_layout.addWidget(create)
        layout.addWidget(btns)


class LoginPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.users = Hub.get_users()
        self.selected_user = None
        self.user_name = None

        self.stack = QStackedLayout()

        self.user_page = UserSelectionPage(self.users, self.user_chosen, self.goto_create_user)
        self.pass_page = PasswordPage(self.goto_select_user, self.check_login)
        self.add_page = AddUserPage(self.create_user, self.goto_select_user)

        self.stack.addWidget(self.user_page)
        self.stack.addWidget(self.pass_page)
        self.stack.addWidget(self.add_page)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(self.stack)

        if not self.users:
            self.stack.setCurrentWidget(self.add_page)
        elif len(self.users) == 1:
            u = self.users[0]
            self.user_chosen(u["username"], u["id"])

    def goto_create_user(self):
        self.stack.setCurrentWidget(self.add_page)

    def goto_select_user(self):
        self.pass_page.password_edit.clear()
        self.stack.setCurrentWidget(self.user_page)

    def user_chosen(self, name, uid):
        self.user_name = name
        self.pass_page.user_bubble.set(name, uid)
        self.stack.setCurrentWidget(self.pass_page)

    def create_user(self):
        name = self.add_page.name_edit.text()
        pwd = self.add_page.pass_edit.text()
        Hub.create_user(name, pwd)
        if Hub.login_user(name, pwd):
            self.on_successful_login()
        else:
            logger.error("login failed")

    def check_login(self):
        pwd = self.pass_page.password_edit.text()
        if Hub.login_user(self.user_name, pwd):
            self.on_successful_login()
        else:
            logger.error("login failed")

    def on_successful_login(self):
        if not Hub.get_user_data():
            name = self.add_page.name_edit.text()
            self.navigator("profile_wizz", user_profile_mode=True)
        else:
            self.navigator("contacts")      