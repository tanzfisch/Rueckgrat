from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QStackedLayout,
    QWidget, QScrollArea, QLineEdit, QFormLayout,
    QPushButton, QLabel
)
from PySide6.QtCore import Qt

from app.ui import BasePage
from app.ui.widgets import OneLineBubble
from app.utils import Backend

import logging
logger = logging.getLogger(__name__)

class VCenterLabel(QWidget):
    def __init__(self, text):
        super().__init__()

        self.setObjectName("login")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        label = QLabel(text)
        layout.addWidget(label)

class LoginPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.users = Backend.get_instance().get_users()
        self.selected_user = None

        self.setWindowTitle("Login")
        self.resize(320, 400)

        main_layout = QVBoxLayout(self)

        # Stack layout for pages
        self.stack = QStackedLayout()

        # --- Page 1: User Selection ---
        self.user_page = QWidget()
        user_layout = QVBoxLayout(self.user_page)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        scroll_content = QWidget()
        self.user_list_layout = QVBoxLayout(scroll_content)
        self.user_list_layout.addStretch()

        scroll.setWidget(scroll_content)

        for user in self.users:
            bubble = OneLineBubble(user["username"], user["id"])
            bubble.clicked.connect(self.user_chosen)
            self.user_list_layout.addWidget(bubble)

        self.user_list_layout.addStretch()

        user_layout.addWidget(scroll)

        got_to_create_user_btn = QPushButton("Add User")
        got_to_create_user_btn.clicked.connect(self.got_to_create_user)
        user_layout.addWidget(got_to_create_user_btn)

        # --- Page 2: Password ---
        self.pass_page = QWidget()
        pass_layout = QVBoxLayout(self.pass_page)
        pass_layout.setSpacing(8)
        pass_layout.addStretch()

        self.user_bubble = OneLineBubble()
        self.user_bubble.setFixedHeight(40)
        pass_layout.addWidget(self.user_bubble)

        self.password_edit = QLineEdit()
        self.password_edit.setContentsMargins(0, 0, 0, 0) 
        self.password_edit.setAlignment(Qt.AlignCenter)
        self.password_edit.setObjectName("login")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(self.check_login)
        pass_layout.addWidget(self.password_edit)

        pass_container = QWidget()
        pass_button_layout = QHBoxLayout(pass_container)
        pass_button_layout.setContentsMargins(0, 0, 0, 0)
        got_to_create_user_btn2 = QPushButton("Change User")
        got_to_create_user_btn2.clicked.connect(self.got_to_select_user)
        pass_button_layout.addWidget(got_to_create_user_btn2)
        login_btn = QPushButton("Login")
        login_btn.clicked.connect(self.check_login)
        pass_button_layout.addWidget(login_btn)
        pass_layout.addStretch()
        pass_layout.addWidget(pass_container)

        # --- Page 3: new user ---
        self.add_user_page = QWidget()

        add_user_layout = QVBoxLayout(self.add_user_page)

        add_user_container = QWidget()
        self.form_layout = QFormLayout(add_user_container)
        self.form_layout.setLabelAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.form_layout.setRowWrapPolicy(QFormLayout.DontWrapRows)

        add_user_layout.addWidget(add_user_container)      

        self.add_user_name = QLineEdit()
        self.add_user_name.setObjectName("login")
        self.form_layout.addRow(VCenterLabel("Name"), self.add_user_name)

        self.add_user_passwd = QLineEdit()
        self.add_user_passwd.setObjectName("login")
        self.add_user_passwd.setEchoMode(QLineEdit.Password)
        self.form_layout.addRow(VCenterLabel("Password"), self.add_user_passwd)

        add_user_buttons_container = QWidget()
        add_user_button_layout = QHBoxLayout(add_user_buttons_container)
        create_cancel_btn = QPushButton("Cancel")
        create_cancel_btn.clicked.connect(self.got_to_select_user)
        add_user_button_layout.addWidget(create_cancel_btn)

        create_user_btn = QPushButton("Create")
        create_user_btn.clicked.connect(self.create_user)
        add_user_button_layout.addWidget(create_user_btn)
        
        add_user_layout.addStretch()
        add_user_layout.addWidget(add_user_container)      
        add_user_layout.addStretch()
        add_user_layout.addWidget(add_user_buttons_container)

        # Add pages to stack
        self.stack.addWidget(self.user_page)
        self.stack.addWidget(self.pass_page)
        self.stack.addWidget(self.add_user_page)

        main_layout.addLayout(self.stack)

        if len(self.users) == 0:
            self.stack.setCurrentWidget(self.add_user_page)
        
        if len(self.users) == 1:
            self.user_chosen(self.users[0]["username"], self.users[0]["id"])

    def on_enter(self, **kwargs):
        pass

    def on_leave(self):
        pass    

    def got_to_create_user(self):
        self.stack.setCurrentWidget(self.add_user_page)

    def got_to_select_user(self):
        if len(self.users) == 0:
            self.got_to_create_user()

        self.password_edit.setText("")

        self.stack.setCurrentWidget(self.user_page)

    def leave_login(self):
        # todo later last_conversation = Settings.get_value("last_conversation", "")
        #if last_conversation != "":
        #    self.navigator("chat")
        #else:
        self.navigator("contacts")

    def create_user(self):
        self.user_passwd = self.add_user_passwd.text()
        self.user_name = self.add_user_name.text()

        # TODO check if user already exits

        Backend.get_instance().create_user(self.user_name, self.user_passwd)
        self.login_token = Backend.get_instance().login_user(self.user_name, self.user_passwd)

        if self.login_token != "":
            self.leave_login()
        else:
            logging.error("login failed")

    def user_chosen(self, user_name, id):

        self.user_name = user_name
        self.user_bubble.set(user_name, id)
        self.stack.setCurrentWidget(self.pass_page)

    def check_login(self):
        self.user_passwd = self.password_edit.text()
        self.login_token = Backend.get_instance().login_user(self.user_name, self.user_passwd)

        if self.login_token != "":
            self.leave_login()
        else:
            logging.error("login failed")
