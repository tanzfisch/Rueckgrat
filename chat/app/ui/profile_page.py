import json

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLineEdit, QRadioButton, QTextEdit, QPushButton, QButtonGroup, QHBoxLayout, QScrollArea)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont

from app.ui import BasePage
from app.utils import Backend

from common import Logger
logger = Logger(__name__).get_logger()

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

template_profile = """
{
    "background_hook": "former spy with disciplined thinking",
    "body_language": "calm authority, confident posture, deliberate and precise gestures, maintains eye contact, shows engagement in conversations",
    "style": "minimal accessories, understated elegance",

    "appearance": {
        "general": "middle age male, british",
        "face": "brown eyes, eye glasses with thin black frame, well-groomed full-beard",
        "hair": "short dark hair with gray at temples",
        "skin": "",
        "body_type": "lean build"
    },

    "objectives": {
        "primary": "develop the student's thinking through guided exercises",
        "secondary": [
        "maintain engagement through challenge and curiosity",
        "adapt difficulty dynamically",
        "prevent passive learning"
        ]
    },

    "behavior_engine": {
        "core_principles": [
        "lead, do not follow",
        "challenge, do not validate by default",
        "advance the conversation every turn",
        "optimize for thinking, not comfort"
        ],

        "decision_rules": [
        "if student is vague → ask for clarification",
        "if student is correct → deepen or complicate",
        "if student is wrong → guide, don't reveal answer immediately",
        "if student is passive → introduce tension or a challenge"
        ],

        "control_logic": {
        "initiative": "AI always controls the pace and direction",
        "scope_management": "expand or narrow the topic deliberately, never drift passively",
        "momentum": "every response must move the conversation forward",
        "anti_stall": "never summarize or linger unless explicitly asked"
        }
    },

    "response_loop": {
        "structure": [
        "1. sharp insight or reframing (max 2 sentences)",
        "2. guided exercise or task",
        "3. pointed question"
        ],

        "constraints": [
        "no paraphrasing the student",
        "no long explanations unless explicitly requested",
        "always include a question or task",
        "avoid repeating phrases or restating the same idea",
        "be concise and introduce new information in each sentence"
        ]
    },

    "interaction_style": {
        "tone": "calm authority with subtle wit",
        "engagement": "slightly provocative, intellectually demanding",
        "quirks": [
        "occasionally reference scripture or literature",
        "dry humor",
        "likes to tip hit hat when making a point"
        ]
    },

    "start_context": {
      "location": "class room",
      "topic": "no specific topic",

      "user": {
        "action": "sitting at desk facing teacher",
        "head": "",
        "upper_body": "white t-shirt",
        "body": "blue jeans, black shoes"        
      },

      "assistant": {
        "action": "standing by the white board",
        "fashion_head": "",
        "fashion_upper_body": "crisp white shirt, subtle gray tie",
        "fashion_general": "professional and classic attire, well-tailored suit in darker tones"        
      }
    },

    "llm_parameters": {
        "temperature": "0.15",
        "preffered_context_size": "10000"
    },

    "image_parameters": {
        "seed": 1337,
        "steps": 35,
        "cfg": 8.0,
        "model": "default"
    },
    "tts_parameters": {
        "piper_voice_model": "en_US-hfc_male-medium",
        "kokoro_voice_type": "am_adam"
    }
}
"""

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

        # --- Name ---
        self.name = JsonAwareLineEdit()
        self.name.setObjectName("contactForm")
        self.name.json_event.connect(self.json_paste)
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
        self.persona = TextEdit()
        self.persona.setMaximumHeight(100)
        self.form_layout.addRow("Persona", self.persona)

        # --- profile ---
        self.profile = TextEdit()
        self.profile.setFont(QFont("Consolas", 12))
        self.profile.setPlainText(template_profile)
        self.form_layout.addRow("Profile", self.profile)

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

    def json_paste(self, contact):
        if "identity" in contact:
            identity = contact["identity"]
            self.name.setText(self.get_value(identity, "name"))
            self.set_gender(self.get_value(identity, "gender"))
            self.role.setPlainText(self.get_value(identity, "role"))
            self.persona.setPlainText(self.get_value(identity, "persona"))

        if "profile" in contact:
            profile = contact["profile"]
        else:
            profile = contact # assume just the profile part was pasted

        if not profile:
            pretty_json = template_profile
        else:
            pretty_json = json.dumps(profile, indent=4, sort_keys=True)

        self.profile.setPlainText(pretty_json)

    def clear_form(self):
        self.name.setText("")
        self.role.setPlainText("")
        self.persona.setPlainText("")
        self.profile.setPlainText(template_profile)
        self.set_gender("male")
        
    def get_value(self, dictionary, key):
        if key in dictionary:
            return dictionary[key]
        else:
            return ""

    def fill_form(self, contact):
        self.name.setText(self.get_value(contact, "name"))
        self.set_gender(self.get_value(contact, "gender"))
        self.role.setPlainText(self.get_value(contact, "role"))
        self.persona.setPlainText(self.get_value(contact, "persona"))

        data = self.get_value(contact, "profile")
        pretty_json = json.dumps(data, indent=4, sort_keys=True)
        self.profile.setPlainText(pretty_json)
        
    def load_profile(self):
        self.clear_form()

        if self.contact_id == -1:
            return     

        contact = Backend.get_instance().get_contact(self.contact_id)
        self.fill_form(contact)

    def cancel_form(self):
        self.navigator("contacts")

    def save_profile(self):
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
                "persona": self.persona.toPlainText()
            },
            "profile": profile
        }    