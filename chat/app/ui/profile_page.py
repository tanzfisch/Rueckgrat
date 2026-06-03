import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QRadioButton, QTextEdit, QPushButton, 
    QButtonGroup, QHBoxLayout, QScrollArea, QFileDialog
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont

from app.ui import BasePage
from app.ui.widgets import ContactHeader
from app.utils import Backend

from common import Logger, Utils
logger = Logger(__name__).get_logger()

class TextEdit(QTextEdit):
    def __init__(self):
        super().__init__()

        self.setObjectName("contactForm")

class ProfilePage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        self.main_layout = QVBoxLayout(self)

        self.contact_header = ContactHeader(navigator, False, True)
        self.contact_header.go_back.connect(self.on_go_back)
        self.main_layout.addWidget(self.contact_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.main_layout.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        self.form_layout = QFormLayout(container)

        # --- Name ---
        self.name = QLineEdit()
        self.name.setObjectName("contactForm")
        self.form_layout.addRow("Name", self.name)

        # --- Gender ---
        self.gender_group = QButtonGroup(self)
        self.male_radio = QRadioButton("Male")
        self.female_radio = QRadioButton("Female")
        self.gender_group.addButton(self.male_radio)
        self.gender_group.addButton(self.female_radio)

        gender_layout = QHBoxLayout()
        gender_layout.addWidget(self.male_radio)
        gender_layout.addWidget(self.female_radio)
        self.form_layout.addRow("Gender", gender_layout)

        # --- Role ---
        self.role = TextEdit()
        self.role.setMaximumHeight(100)
        self.form_layout.addRow("Role", self.role)

        # --- Persona ---
        self.personality = TextEdit()
        self.personality.setMaximumHeight(100)
        self.form_layout.addRow("Persona", self.personality)

        # --- profile ---
        self.profile = TextEdit()
        self.profile.setFont(QFont("Consolas", 12))
        self.form_layout.addRow("Profile", self.profile)

        # --- BUTTONS ---
        button_container = QWidget()
        main_layout = QVBoxLayout(button_container)

        top_layout = QVBoxLayout()
        main_layout.addLayout(top_layout)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._on_load)
        top_layout.addWidget(load_btn)

        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._on_export)
        top_layout.addWidget(export_btn)

        bottom_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._on_cancel)
        bottom_layout.addWidget(cancel_btn)

        submit_btn = QPushButton("Save Profile")
        submit_btn.clicked.connect(self._on_save)
        bottom_layout.addWidget(submit_btn)
        main_layout.addLayout(bottom_layout)

        self.main_layout.addWidget(button_container)

    def on_go_back(self):
        self.navigator("contacts")        

    def clear_form(self):
        self.name.setText("")
        self.role.setPlainText("")
        self.personality.setPlainText("")
        self.profile.setPlainText("")
        self.set_gender("male")
        
    def get_value(self, dictionary, key):
        if key in dictionary:
            return dictionary[key]
        else:
            return ""

    def fill_form(self, contact):
        self.name.setText(Utils.get_nested_value(contact, ["identity", "name"], ""))
        self.set_gender(Utils.get_nested_value(contact, ["identity", "gender"], ""))
        self.role.setPlainText(Utils.get_nested_value(contact, ["identity", "role"], ""))
        self.personality.setPlainText(Utils.get_nested_value(contact, ["identity", "personality"], ""))

        data = Utils.get_nested_value(contact, ["profile"], "")
        pretty_json = json.dumps(data, indent=4)
        self.profile.setPlainText(pretty_json)
        
    def load_profile(self):
        self.clear_form()

        if self.contact_id == -1:
            return     

        contact = Backend.get_instance().get_contact(self.contact_id)
        self.fill_form(contact)

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile")
        if path:
            with open(path, 'r') as file:
                data = json.load(file)
                self.fill_form(data)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Profile")
        if path:
            with open(path, 'w') as file:
                data = self.get_data()
                json.dump(data, file, indent=4)

    def _on_cancel(self):
        self.navigator("contacts")

    def _on_save(self):
        if self.contact_id == -1:
            self.contact_id = Backend.get_instance().create_contact()

        data = self.get_data()
        Backend.get_instance().update_contact(self.contact_id, data)
        self.navigator("contacts")

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        self.load_profile()

    def on_leave(self):
        pass                 

    def add_rule(self):
        text = self.rule_input.text().strip()
        if text:
            self.rules_list.addItem(text)
            self.rule_input.clear()

    def remove_rule(self):
        selected = self.rules_list.currentRow()
        if selected >= 0:
            self.rules_list.takeItem(selected)

    def set_gender(self, gender: str):
        if not gender:
            return
        
        if gender.lower() == "male":
            self.male_radio.setChecked(True)
        elif gender.lower() == "female":
            self.female_radio.setChecked(True)

    def get_data(self):
        selected_button = self.gender_group.checkedButton()
        if selected_button:
            gender = selected_button.text().lower()

        profile = json.loads(self.profile.toPlainText())

        return {
            "identity": {
                "name": self.name.text(),
                "gender": gender,
                "role": self.role.toPlainText(),
                "personality": self.personality.toPlainText()
            },
            "profile": profile
        }    