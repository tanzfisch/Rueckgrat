import json
import random

from PySide6.QtWidgets import (
    QVBoxLayout, QStackedLayout, QWidget, QPushButton, QLabel,
    QHBoxLayout, QLineEdit, QTextEdit, QFormLayout, QComboBox
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

from app.utils import Backend
from app.ui import BasePage
from app.ui.widgets import ContactHeader, LabeledSlider, RowSelector, PlainTextEdit

from common import Logger
logger = Logger(__name__).get_logger()

class ProfilePage(QWidget):
    male_names = [
        "Hans", "Marcus", "Oliver", "Lukas", "Leon", "Ben", "David", "Tim", "Niklas", "Max",
        "Felix", "Lennart", "Johannes", "Paul", "Simon", "Jonas", "Moritz", "Tom", "Leonard",
        "Nils", "Luca", "Emil", "Jakob", "Oskar", "Henrik", "Alexander", "Lars", "Elias",
        "Samuel", "Tobias", "Finn", "Mika", "Noah", "Arne", "Lennard", "Linus",
        "Timo", "Jasper", "Rafael", "Lenny", "Fynn", "Anton", "Levi", "Kian", "Liam", "Matti",
        "Caspian", "Ethan", "Jax", "Kai", "Milo", "Nolan", "Quinn", "Rylan", "Soren",
        "Tristan", "Zane", "Aiden", "Brayden", "Cameron", "Declan", "Evan", "Finnley",
        "Grey", "Hunter", "Ian", "Jayden", "Kaden", "Landon", "Maverick", "Nathan",
        "Parker", "Quentin", "Rowan", "Sawyer", "Theo", "Vincent", "Willow",
        "Xander", "Yanni", "Zachary", "Adrian", "Bennett", "Caleb", "Dante", "Easton",
        "Finnian", "Gabe", "Hudson", "Iker", "Jaxon", "Mason", "Nico", "Oakley",
        "Akira", "Haruto", "Ren", "Yuki", "Sora", "Takumi", "Hiro", "Kenji", "Daichi", "Riku",
        "Minho", "Jisoo", "Hyun", "Taeyang", "Joon", "Sungmin", "Jiho", "Donghae",
        "Wei", "Jian", "Hao", "Jun", "Ming", "Tao", "Chen", "Zhen", "Yuan", "Bo",
        "Arjun", "Rohan", "Aarav", "Vihaan", "Kabir", "Dev", "Kiran", "Raj", "Aryan", "Ishan",
        "Nguyen", "Bao", "Minh", "An", "Kiet", "Azlan", "Rizky", "Farhan", "Imran", "Zayn",
        "Kwame", "Kofi", "Kwaku", "Yaw", "Kojo", "Kwabena", "Kweku", "Tunde", "Ade", "Chike",
        "Emeka", "Chinedu", "Oluwaseun", "Oluwafemi", "Ikenna", "Babatunde", "Adebayo",
        "Thabo", "Sipho", "Lethabo", "Neo", "Mandla", "Sibusiso", "Andile", "Kagiso",
        "Tumelo", "Rashid", "Zuberi", "Jelani", "Omari", "Malik", "Hakim", "Abdul",
        "Faraji", "Jabari", "Amari", "Kamau", "Mosi", "Sekou", "Khamisi", "Baraka",
        "Ekon", "Nuru", "Obinna", "Chuma", "Dumisani", "Siyabonga", "Vusi"
    ]

    female_names = [
        "Anna", "Emma", "Sophie", "Mia", "Hannah", "Lena", "Leonie", "Marie", "Laura", "Sarah",
        "Clara", "Johanna", "Paula", "Nina", "Julia", "Amelie", "Charlotte", "Ella", "Emily",
        "Lisa", "Mila", "Luisa", "Alina", "Helena", "Katharina", "Lina", "Marlene", "Nora",
        "Sina", "Theresa", "Vanessa", "Victoria", "Zoe", "Elisa", "Greta", "Isabel", "Jana",
        "Kim", "Lara", "Maja", "Naomi", "Olivia", "Pia", "Romy", "Selina", "Tabea",
        "Vivien", "Yara", "Alicia", "Bianca", "Celine", "Daria", "Elena", "Fiona", "Giulia",
        "Hailey", "Isla", "Jasmine", "Kayla", "Layla", "Madison", "Natalie", "Ophelia",
        "Penelope", "Quinn", "Ruby", "Scarlett", "Taylor", "Uma", "Valerie", "Willow",
        "Xenia", "Yvonne", "Zara", "Aria", "Bella", "Chloe", "Delilah", "Eva", "Freya",
        "Gabriella", "Hazel", "Ivy", "Jade", "Kylie", "Lillian", "Melody", "Nova", "Oakley",
        "Paisley", "Riley", "Savannah", "Trinity", "Violet", "Winter", "Zoey",
        "Aiko", "Akari", "Emi", "Hana", "Kaori", "Mei", "Sakura", "Yui", "Rin", "Nanami",
        "Jiwoo", "Minji", "Soojin", "Hyejin", "Yuna", "Jihye", "Nari", "Seoyeon",
        "Xinyi", "Meilin", "Jing", "Li Na", "Qiao", "Yue", "Xia", "Lan", "Chenxi", "Ting",
        "Ananya", "Diya", "Isha", "Kavya", "Meera", "Priya", "Riya", "Saanvi", "Tara", "Zoya",
        "Anh", "Linh", "Mai", "Thao", "Vy", "Alya", "Farah", "Nadia", "Safiya", "Zarina",
        "Amina", "Zainab", "Fatou", "Aisha", "Nia", "Imani", "Zuri", "Safiya", "Abeni",
        "Adesuwa", "Chiamaka", "Oluwaseyi", "Temiloluwa", "Ifeoma", "Ngozi", "Amara",
        "Thandi", "Lindiwe", "Nomvula", "Busisiwe", "Kagiso", "Neo", "Lerato",
        "Rethabile", "Tshepiso", "Ayanda", "Zanele", "Siphesihle",
        "Jelani", "Malika", "Hadiya", "Jamila", "Samira", "Nala", "Zahara",
        "Asha", "Bahati", "Eshe", "Kesi", "Malaika", "Nuru", "Sanaa", "Zola",
        "Obioma", "Chinwe", "Adanna", "Ebele", "Uduak", "Yewande", "Funmi"        
    ]

    male_ages = {
        "18": "app/icons/male_teen_light.png",
        "22": "app/icons/male_20s_light.png",
        "27": "app/icons/male_30s_light.png",
        "45": "app/icons/male_40s_light.png",
        "60": "app/icons/male_old_light.png"
    }

    female_ages = {
        "18": "app/icons/female_teen_light.png",
        "22": "app/icons/female_20s_light.png",
        "27": "app/icons/female_30s_light.png",
        "45": "app/icons/female_40s_light.png",
        "60": "app/icons/female_old_light.png"
    }

    hair_color = {
        "black": "app/icons/hair_black.png",
        "dark brown": "app/icons/hair_dark_brown.png",
        "brown": "app/icons/hair_brown.png",
        "bright brown": "app/icons/hair_bright_brown.png",
        "blonde": "app/icons/hair_blonde.png",
        "red": "app/icons/hair_red.png",
        "gray": "app/icons/hair_gray.png"
    }

    eye_color = {
        "black": "app/icons/eye_black.png",
        "dark brown": "app/icons/eye_dark_brown.png",
        "bright brown": "app/icons/eye_bright_brown.png",
        "green": "app/icons/eye_green.png",
        "blue": "app/icons/eye_blue.png",
        "gray": "app/icons/eye_gray.png",
        "red": "app/icons/eye_red.png"
    }

    ethnicity = {
        "East Asian": "",
        "South Asian": "",
        "Southeast Asian": "",
        "Middle Eastern": "",
        "African": "",
        "European": "",
        "Latino": "",
        "Native American": "",
        "Oceanian": ""
    }

    body_type = {
        "underweight": "app/icons/body_underweight_light.png",
        "athletic": "app/icons/body_normal_light.png",
        "curvy": "app/icons/body_overweight_light.png",
        "overweight": "app/icons/body_obese_light.png",
        "obese": "app/icons/body_morbidly_obese_light.png",
    }    

    def __init__(self, profile: dict = None, name: str = None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.name = name

        self._setup_ui()


    def _setup_ui(self):
        layout = QVBoxLayout(self)

        container = QWidget()
        layout.addWidget(container)
        self.form_layout = QFormLayout(container)
        self.form_layout.setSpacing(5)
        
        self.name_input = QLineEdit()

        if self.name:
            self.name_input.setText(self.name)
            self.name_input.setEnabled(False)
        else:
            if self.profile:
                self.name_input.setText(self.profile["name"])
            else:
                self.name_input.setText(random.choice(self.male_names))

        self.form_layout.addRow("Name", self.name_input)

        self.gender = RowSelector({"male": "app/icons/male_light.png", "female": "app/icons/female_light.png"})
        self.gender.selection_changed.connect(self.on_gender_changed)
        if not self.profile:
            self.gender.select("male")
        else:
            self.gender.select(self.profile["gender"])
        self.form_layout.addRow("Gender", self.gender)

        self.age = RowSelector(self.male_ages)
        if not self.profile:
            self.age.select("22")
        else:
            age = self.profile["age"]
            ages = [int(k) for k in self.male_ages.keys()]
            closest = min(ages, key=lambda x: abs(x - age))
            self.age.select(str(closest))
        self.form_layout.addRow("Age", self.age)

        self.hair = RowSelector(self.hair_color, True, 7)
        if not self.profile:
            self.hair.select_random()
        else:
            self.hair.select(self.profile["hair_color"])
        self.form_layout.addRow("Hair", self.hair)

        self.eye = RowSelector(self.eye_color, True, 7)
        if not self.profile:
            self.eye.select_random()
        else:
            self.eye.select(self.profile["eye_color"])
        self.form_layout.addRow("Eyes", self.eye)

        self.ethnicity = RowSelector(self.ethnicity, False, 3)
        if not self.profile:
            self.ethnicity.select_random()
        else:
            self.ethnicity.select(self.profile["ethnicity"])
        self.form_layout.addRow("Ethnicity", self.ethnicity)

        self.body_type = RowSelector(self.body_type, True, 5)
        if not self.profile:
            self.body_type.select_random()
        else:
            self.body_type.select(self.profile["body_type"])
        self.form_layout.addRow("Body Type", self.body_type)

        self.backstory = PlainTextEdit()
        self.backstory.setObjectName("contactForm")
        self.backstory.setFont(QFont("Consolas", 12))
        self.backstory.setPlaceholderText("Type optional backstory here ...")
        if self.profile:
            self.backstory.setPlainText(self.profile["backstory"])
        self.form_layout.addRow("Backstory", self.backstory)

        layout.addStretch()

    def on_gender_changed(self, gender: str):
        if gender == "male":
            if not self.profile:
                self.name_input.setText(random.choice(self.male_names))
            self.age.update_images(self.male_ages)
        else:
            if not self.profile:
                self.name_input.setText(random.choice(self.female_names))
            self.age.update_images(self.female_ages)

    def get_values(self):
        result = {
            "name" : self.name_input.text(),
            "gender" : self.gender.get_selected(),
            "age" : int(self.age.get_selected()),
            "hair_color" : self.hair.get_selected(),
            "eye_color" : self.eye.get_selected(),
            "ethnicity" : self.ethnicity.get_selected(),
            "body_type" : self.body_type.get_selected(),
            "backstory" : self.backstory.toPlainText()
        }

        return result

class PersonalityPage(QWidget):
    roles = [
        "Assistant", "Friend", "Partner","Coach", 
        "Therapist", "Mentor", "Rival", "Companion", 
        "Motivator", "Teacher", "Muse", "Critic", 
        "Cheerleader", "Pet"
    ]

    perosnality_attributes = {
        "Warmth": {
            "tags": ["cold", "warm"],
            "trait": ["cold", "distant", "reserved", "indifferent", "approachable", "friendly", "warm"]
        },
        "Formality": {
            "tags": ["casual", "formal"],
            "trait": ["informal", "casual", "semi-casual", "semi-formal", "very formal", "extremely formal", "excessively formal"],
        }, 
        "Energy": {
            "tags": ["calm", "energetic"],
            "trait": ["calm", "composed", "collected", "alert", "enthusiastic", "energetic", "passionate"]
        }, 
        "Humor": {
            "tags": ["serious", "funny"],
            "trait": ["serious", "thoughtful", "analytical", "humorous", "playful", "witty", "funny"]
        },
        "Directness": {
            "tags": ["gentle", "blunt"],
            "trait": ["gentle", "mild", "soft-spoken", "straightforward", "frank", "direct", "blunt"]
        },
        "Familiarity": {
            "tags": ["stranger", "best friend"],
            "trait": ["stranger", "acquaintance", "companion", "familiar", "friend", "close friend", "best friend"]
        },
        "Power": {
            "tags": ["submissive", "dominant"],
            "trait": ["submissive", "accommodating", "cooperative", "influential", "assertive", "confident", "dominant"]
        },
        "Initiative": {
            "tags": ["reactive", "active"],
            "trait": ["reactive", "responsive", "adaptable", "proactive", "initiative-taking", "pioneering", "active"]
        },
        "Honesty": {
            "tags": ["agreeable", "liar"],
            "trait": ["agreeable", "cooperative", "accommodating", "assertive", "confrontational", "challenging", "liar"]
        },
        "Intent": {
            "tags": ["manipulative", "benevolent"],
            "trait": ["manipulative", "exploitative", "self-serving", "prudent", "empathetic", "generous", "benevolent"]
        }
    }
   
    def __init__(self, parent=None):
        super().__init__(parent)

        self.perosnality_sliders = {}

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        container = QWidget()
        layout.addWidget(container)
        self.form_layout = QFormLayout(container)
        self.form_layout.setSpacing(5)

        self.role = QComboBox()
        self.role.addItems(self.roles)
        self.role.setEditable(True)
        self.role.setMaxVisibleItems(5)
        self.form_layout.addRow("Role", self.role)

        for name, item in self.perosnality_attributes.items():
            left = item["tags"][0]
            right = item["tags"][1]
            slider = LabeledSlider(
                left_text=left,
                right_text=right,
                range_min=0,
                range_max=len(item["trait"])-1,
                start_value=len(item["trait"])/2
            )

            self.form_layout.addRow(name, slider)
            self.perosnality_sliders[name] = slider

        self.objective = QTextEdit()
        self.objective.setObjectName("contactForm")
        self.objective.setFont(QFont("Consolas", 12))
        self.objective.setText("Be helpful")
        self.form_layout.addRow("Objective", self.objective)

        self.sfw = RowSelector({"SFW": "app/icons/sfw_light.png", "NSFW": "app/icons/nsfw_light.png"}, False)
        self.sfw.select("SFW")
        self.form_layout.addRow("NSFW", self.sfw)        

        layout.addStretch()

    def get_values(self):
        personality = ""
        for name, item in self.perosnality_attributes.items():
            value = self.perosnality_sliders[name].get_value()
            trait = item["trait"][value]
            if trait != "":
                if personality != "":
                    personality += ", "
                personality += trait        
        
        result = {
            "role": self.role.currentText(),
            "personality": personality,
            "objective": self.objective.toPlainText(),
            "sfw": self.sfw.get_selected()
        }        

        return result   
    
class ProgressPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        progress_label = QLabel("Please wait...")
        progress_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(progress_label)

class ProfileWizard(BasePage):
    selected_role = ""

    def __init__(self, navigator):
        super().__init__(navigator)
        self.main_layout = QVBoxLayout(self)        

        self.contact_header = ContactHeader(navigator, False)
        self.contact_header.go_back.connect(self.on_go_back)
        self.main_layout.addWidget(self.contact_header)
        
        self.stack = QStackedLayout()        
        self.main_layout.addLayout(self.stack)

        self.current_index = 0

        self.pages = []
        
        # --- BUTTONS ---
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)

        self.back_btn = QPushButton("...")
        self.back_btn.clicked.connect(self.prev_page)
        button_layout.addWidget(self.back_btn)

        self.next_btn = QPushButton("...")
        self.next_btn.clicked.connect(self.next_page)
        button_layout.addWidget(self.next_btn)

        self.main_layout.addWidget(button_container)

        self.update_buttons()

    def on_go_back(self):
        self.navigator("contacts")

    def add_page(self, widget):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(widget)
        self.pages.append(page)
        self.stack.addWidget(page)

    def clear_pages(self):
        while self.pages:
            page = self.pages.pop()
            self.stack.removeWidget(page)
            page.deleteLater()

    def next_page(self):
        if self.current_index < len(self.pages) - 1:
            self.current_index += 1
            self.stack.setCurrentIndex(self.current_index)
            self.update_buttons()        
        else:
            profile = self.profile_page.get_values()

            if not self.user_profile_mode:
                personality = self.personality_page.get_values()
                prompt = {
                    "generate_profile": {
                        "profile": profile,
                        "personality": personality
                    }
                }
                Backend.generate(prompt)
            else:
                data = {
                    "profile": json.dumps(profile)
                }
                Backend.update_user_data(data)
                self.navigator("contacts")

    def prev_page(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.stack.setCurrentIndex(self.current_index)
            self.update_buttons()

    def update_buttons(self):
        back_button = {
            0: [False, ""],
            1: [True, "Back"],
            2: [False, ""]
        }
        self.back_btn.setVisible(back_button[self.current_index][0])
        self.back_btn.setText(back_button[self.current_index][1])

        next_button = {
            0: [True, "Next"],
            1: [True, "Finish"],
            2: [False, ""]
        }
        self.next_btn.setVisible(next_button[self.current_index][0])
        self.next_btn.setText(next_button[self.current_index][1])

    def on_enter(self, **kwargs):
        self.user_profile_mode = kwargs.get("user_profile_mode", False)

        self.clear_pages()

        if self.user_profile_mode:
            data = Backend.get_user_data()
            name = Backend.get_user_name()
            if data and "profile" in data:
                profile = data["profile"]
            else:
                profile = None
                
            self.profile_page = ProfilePage(profile=profile, name=name)

            self.add_page(self.profile_page)
        else:
            self.profile_page = ProfilePage()
            self.add_page(self.profile_page)

            self.personality_page = PersonalityPage()
            self.add_page(self.personality_page)

            #self.progress_page = ProgressPage()
            #self.add_page(self.progress_page)

        if not self.user_profile_mode:
            Backend.register_incomming_message(self.on_incomming_message)

    def on_leave(self):
        if not self.user_profile_mode:
            Backend.unregister_incomming_message(self.on_incomming_message)

    def on_incomming_message(self, msg: dict):
        try:
            if "contact_id" in msg:
                contact_id = msg["contact_id"]
                self.navigator("contacts")
        except Exception as e:
            logger.error(f"failed to handle incomming message: {repr(e)}")

