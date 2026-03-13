import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QRadioButton, QTextEdit,
    QSpinBox, QDoubleSpinBox, QPushButton, QListWidget, QButtonGroup,
    QHBoxLayout, QLabel, QScrollArea
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence

from app.ui import BasePage
from app.utils import backend

class TextEdit(QTextEdit):
    def __init__(self):
        super().__init__()

        self.setObjectName("contactForm")

class JsonAwareLineEdit(QLineEdit):
    json_event = Signal(dict)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.textChanged.connect(self.on_text_changed)

    def on_text_changed(self, text: str):
        try:
            data = json.loads(text)
            self.json_event.emit(data)
        except json.JSONDecodeError:
            pass        


class ProfilePage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        main_layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        self.form_layout = QFormLayout(container)

        # --- TEXT FIELDS ---
        self.name = JsonAwareLineEdit()
        self.name.setObjectName("contactForm")
        self.name.json_event.connect(self.json_paste)
        self.form_layout.addRow("Name", self.name)

        self.gender_group = QButtonGroup(self)

        self.male_radio = QRadioButton("Male")
        self.female_radio = QRadioButton("Female")

        self.gender_group.addButton(self.male_radio)
        self.gender_group.addButton(self.female_radio)

        gender_layout = QHBoxLayout()
        gender_layout.addWidget(self.male_radio)
        gender_layout.addWidget(self.female_radio)

        self.form_layout.addRow("Gender", gender_layout)

        self.attributes = TextEdit()
        self.form_layout.addRow("Attributes", self.attributes)

        self.core_traits = TextEdit()
        self.form_layout.addRow("Core Traits", self.core_traits)

        self.quirks = TextEdit()
        self.form_layout.addRow("Quirks", self.quirks)

        self.distinctive_feature = TextEdit()
        self.form_layout.addRow("Distinctive Feature", self.distinctive_feature)

        self.purpose = TextEdit()
        self.form_layout.addRow("Purpose", self.purpose)

        self.relationship = TextEdit()
        self.form_layout.addRow("Relationship", self.relationship)

        self.long_term_commitment = TextEdit()
        self.form_layout.addRow("Long-Term Commitment", self.long_term_commitment)

        self.current_status = TextEdit()
        self.form_layout.addRow("Current Status", self.current_status)

        self.secrets = TextEdit()
        self.form_layout.addRow("Secrets", self.secrets)

        self.limits = TextEdit()
        self.form_layout.addRow("Limits", self.limits)

        self.location = TextEdit()
        self.form_layout.addRow("Location", self.location)

        # --- RULES LIST ---
        self.rules_list = QListWidget()
        self.rules_list.setFixedHeight(100)
        self.rule_input = QLineEdit()
        self.rule_input.setObjectName("contactForm")
        self.add_rule_btn = QPushButton("Add Rule")
        self.remove_rule_btn = QPushButton("Remove Selected Rule")

        rule_layout = QVBoxLayout()
        rule_layout.addWidget(QLabel("Rules"))
        rule_layout.addWidget(self.rules_list)

        rule_input_layout = QHBoxLayout()
        rule_input_layout.addWidget(self.rule_input)
        rule_input_layout.addWidget(self.add_rule_btn)
        rule_layout.addLayout(rule_input_layout)
        rule_layout.addWidget(self.remove_rule_btn)

        self.form_layout.addRow(rule_layout)

        self.add_rule_btn.clicked.connect(self.add_rule)
        self.remove_rule_btn.clicked.connect(self.remove_rule)

        # --- CHAT SETTINGS ---
        self.chat_temperature = QLineEdit()
        self.chat_temperature.setText("0.7")
        self.form_layout.addRow("Chat Temperature", self.chat_temperature)

        # --- VISUAL SETTINGS ---
        self.visual_prompt = TextEdit()
        self.form_layout.addRow("Visual Prompt", self.visual_prompt)

        self.visual_negative_prompt = TextEdit()
        self.form_layout.addRow("Visual Negative Prompt", self.visual_negative_prompt)

        self.visual_seed = QLineEdit()
        self.visual_seed.setText("1337")
        self.form_layout.addRow("Visual Seed", self.visual_seed)

        self.visual_cfg = QLineEdit()
        self.visual_cfg.setText("10.0")
        self.form_layout.addRow("Visual CFG", self.visual_cfg)

        self.visual_steps = QLineEdit()
        self.visual_steps.setText("30")
        self.form_layout.addRow("Visual Steps", self.visual_steps)

        # --- AUDIO SETTINGS ---
        self.piper_voice_model = QLineEdit()
        self.piper_voice_model.setText("")
        self.form_layout.addRow("Piper Model", self.piper_voice_model)

        self.kokoro_voice_type = QLineEdit()
        self.kokoro_voice_type.setText("")
        self.form_layout.addRow("Kokoro Voice", self.kokoro_voice_type)        

        # --- SUBMIT BUTTON ---
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_form)
        button_layout.addWidget(self.cancel_btn)

        self.submit_btn = QPushButton("Save Profile")
        self.submit_btn.clicked.connect(self.save_profile)
        button_layout.addWidget(self.submit_btn)

        main_layout.addWidget(button_container)

    def json_paste(self, data):
        self.fill_form(data)

    def clear_form(self):
        self.name.setText("")
        self.attributes.setPlainText("")
        self.core_traits.setPlainText("")
        self.quirks.setPlainText("")
        self.distinctive_feature.setPlainText("")
        self.purpose.setPlainText("")
        self.relationship.setPlainText("")
        self.long_term_commitment.setPlainText("")
        self.current_status.setPlainText("")
        self.secrets.setPlainText("")
        self.limits.setPlainText("")
        self.location.setPlainText("")
        self.rules_list.clear()
        self.chat_temperature.setText("0.7")
        self.piper_voice_model.setText("")
        self.kokoro_voice_type.setText("")
        self.visual_prompt.setPlainText("")
        self.visual_negative_prompt.setPlainText("")
        self.visual_seed.setText("1337")
        self.visual_cfg.setText("10")
        self.visual_steps.setText("30")

    def fill_form(self, contact):
        self.name.setText(contact["name"])
        self.set_gender(contact["gender"])
        self.attributes.setPlainText(contact["attributes"])
        self.core_traits.setPlainText(contact["core_traits"])
        self.quirks.setPlainText(contact["quirks"])
        self.distinctive_feature.setPlainText(contact["distinctive_feature"])
        self.purpose.setPlainText(contact["purpose"])
        self.relationship.setPlainText(contact["relationship"])
        self.long_term_commitment.setPlainText(contact["long_term_commitment"])
        self.current_status.setPlainText(contact["current_status"])
        self.secrets.setPlainText(contact["secrets"])
        self.limits.setPlainText(contact["limits"])
        self.location.setPlainText(contact["location"])

        self.rules_list.clear()
        if contact["rules"]:
            rules = contact["rules"]
            for rule in rules:
                self.rules_list.addItem(rule)

        self.chat_temperature.setText(str(contact["chat_temperature"]))
        self.piper_voice_model.setText(contact["piper_voice_model"])
        self.kokoro_voice_type.setText(contact["kokoro_voice_type"])
        self.visual_prompt.setPlainText(contact["visual_prompt"])
        self.visual_negative_prompt.setPlainText(contact["visual_negative_prompt"])
        self.visual_seed.setText(str(contact["visual_seed"]))
        self.visual_cfg.setText(str(contact["visual_cfg"]))
        self.visual_steps.setText(str(contact["visual_steps"]))

    def load_profile(self):
        self.clear_form()

        if self.contact_id == -1:
            return     

        contact = backend.get_contact(self.contact_id)
        self.fill_form(contact)

    def cancel_form(self):
        self.navigator("contacts")

    def save_profile(self):
        if self.contact_id == -1:
            self.contact_id = backend.create_contact()

        data = self.get_data()
        backend.update_contact(self.contact_id, data)
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

        # todo check for ranges

        return {
            "name": self.name.text(),
            "gender": gender,
            "attributes": self.attributes.toPlainText(),
            "core_traits": self.core_traits.toPlainText(),
            "quirks": self.quirks.toPlainText(),
            "distinctive_feature": self.distinctive_feature.toPlainText(),
            "purpose": self.purpose.toPlainText(),
            "relationship": self.relationship.toPlainText(),
            "long_term_commitment": self.long_term_commitment.toPlainText(),
            "current_status": self.current_status.toPlainText(),
            "secrets": self.secrets.toPlainText(),
            "limits": self.limits.toPlainText(),
            "location": self.location.toPlainText(),
            "rules": [self.rules_list.item(i).text() for i in range(self.rules_list.count())],
            "chat_temperature": float(self.chat_temperature.text()),
            "piper_voice_model": self.piper_voice_model.text(),
            "kokoro_voice_type": self.kokoro_voice_type.text(),
            "visual_prompt": self.visual_prompt.toPlainText(),
            "visual_negative_prompt": self.visual_negative_prompt.toPlainText(),
            "visual_seed": int(self.visual_seed.text()),
            "visual_cfg": float(self.visual_cfg.text()),
            "visual_steps": int(self.visual_steps.text())
        }    