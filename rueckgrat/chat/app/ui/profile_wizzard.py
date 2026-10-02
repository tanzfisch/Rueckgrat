import json
import os
import random
import flet as ft
from app.ui.theme import STYLES

from app.utils import Hub
from app.ui import BasePage
from app.ui.widgets import ContactHeader, LabeledSlider, RowSelector
from app.common import get_logger, Utils

logger = get_logger()

LABEL_WIDTH = 80
ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"

class WizardProfilePage(ft.Column):
    male_names = [
        "Kwesi", "Nnamdi", "Chidi", "Olumide", "Ayodele", "Segun", "Kunle", "Dayo",
        "Themba", "Bongani", "Sizwe", "Lwazi", "Lungelo", "Nkosi", "Mpho", "Tshepo",
        "Tendai", "Tafadzwa", "Farai", "Tinashe", "Mwangi", "Otieno", "Wekesa", "Abebe",
        "Yonas", "Haile", "Chukwudi", "Ifeanyi", "Obiora", "Chinonso",        
        "Matteo", "Andreas", "Stefan", "Christian", "Daniel", "Sebastian", "Florian", "Philipp",
        "Julian", "Fabian", "Konstantin", "Matthias", "Patrick", "Marco", "Giovanni", "Alessandro",
        "Francesco", "Pierre", "Antoine", "Louis", "Hugo", "Erik", "Magnus", "Anders",
        "Piotr", "Nikolai", "Viktor", "Casper", "Sven", "Bjorn",
        "Hans", "Marcus", "Oliver", "Lukas", "Leon", "Ben", "David", "Tim", "Niklas", "Max",
        "Felix", "Lennart", "Johannes", "Paul", "Simon", "Jonas", "Moritz", "Tom", "Leonard",
        "Nils", "Luca", "Emil", "Jakob", "Oskar", "Henrik", "Alexander", "Lars", "Elias",
        "Samuel", "Tobias", "Finn", "Mika", "Noah", "Arne", "Lennard", "Linus", "Martin",
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
        "Ekon", "Nuru", "Obinna", "Chuma", "Dumisani", "Siyabonga", "Vusi", "Luke",
    ]

    female_names = [
        "Chioma", "Nneka", "Adaeze", "Yetunde", "Folake", "Adenike", "Ama", "Akua",
        "Adwoa", "Efua", "Nandi", "Zinhle", "Nobuhle", "Amahle", "Palesa", "Dineo",
        "Refilwe", "Rudo", "Chipo", "Tariro", "Wanjiku", "Akinyi", "Nyambura", "Chebet",
        "Oluchi", "Chisom", "Titilayo", "Bolanle", "Liyana", "Thandiwe",        
        "Sophia", "Emilia", "Frieda", "Ida", "Mathilda", "Franziska", "Annika", "Ingrid",
        "Astrid", "Frederike", "Chiara", "Giulia", "Francesca", "Camille", "Claire", "Elise",
        "Margot", "Adele", "Ines", "Carmen", "Lucia", "Elena", "Klara", "Thea",
        "Sigrid", "Linnea", "Katja", "Anja", "Petra", "Monika", "Daphne", "Madelein",
        "Anna", "Emma", "Sophie", "Mia", "Hannah", "Lena", "Leonie", "Marie", "Laura", "Sarah",
        "Clara", "Johanna", "Paula", "Nina", "Julia", "Amelie", "Charlotte", "Ella", "Emily",
        "Lisa", "Mila", "Luisa", "Alina", "Helena", "Katharina", "Lina", "Marlene", "Nora",
        "Sina", "Theresa", "Vanessa", "Victoria", "Zoe", "Elisa", "Greta", "Isabel", "Jana",
        "Kim", "Lara", "Maja", "Naomi", "Olivia", "Pia", "Romy", "Selina", "Tabea",
        "Vivien", "Yara", "Alicia", "Bianca", "Celine", "Daria", "Elena", "Fiona", "Giulia",
        "Hailey", "Isla", "Jasmine", "Kayla", "Layla", "Madison", "Natalie", "Ophelia",
        "Penelope", "Quinn", "Ruby", "Scarlett", "Taylor", "Uma", "Valerie", "Willow",
        "Xenia", "Yvonne", "Zara", "Aria", "Bella", "Chloe", "Delilah", "Eva", "Freya",
        "Gabrielle", "Hazel", "Ivy", "Jade", "Kylie", "Lillian", "Melody", "Nova", "Oakley",
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
        "Obioma", "Chinwe", "Adanna", "Ebele", "Uduak", "Yewande", "Funmi",
    ]

    male_ages = {
        "18": f"{ASSETS_DIR}/icons/male_teen_light.png",
        "22": f"{ASSETS_DIR}/icons/male_20s_light.png",
        "27": f"{ASSETS_DIR}/icons/male_30s_light.png",
        "45": f"{ASSETS_DIR}/icons/male_40s_light.png",
        "60": f"{ASSETS_DIR}/icons/male_old_light.png",
    }

    female_ages = {
        "18": f"{ASSETS_DIR}/icons/female_teen_light.png",
        "22": f"{ASSETS_DIR}/icons/female_20s_light.png",
        "27": f"{ASSETS_DIR}/icons/female_30s_light.png",
        "45": f"{ASSETS_DIR}/icons/female_40s_light.png",
        "60": f"{ASSETS_DIR}/icons/female_old_light.png",
    }

    hair_color = {
        "black": f"{ASSETS_DIR}/icons/hair_black.png",
        "dark brown": f"{ASSETS_DIR}/icons/hair_dark_brown.png",
        "brown": f"{ASSETS_DIR}/icons/hair_brown.png",
        "bright brown": f"{ASSETS_DIR}/icons/hair_bright_brown.png",
        "blonde": f"{ASSETS_DIR}/icons/hair_blonde.png",
        "red": f"{ASSETS_DIR}/icons/hair_red.png",
        "gray": f"{ASSETS_DIR}/icons/hair_gray.png",
    }

    eye_color = {
        "black": f"{ASSETS_DIR}/icons/eye_black.png",
        "dark brown": f"{ASSETS_DIR}/icons/eye_dark_brown.png",
        "bright brown": f"{ASSETS_DIR}/icons/eye_bright_brown.png",
        "green": f"{ASSETS_DIR}/icons/eye_green.png",
        "blue": f"{ASSETS_DIR}/icons/eye_blue.png",
        "gray": f"{ASSETS_DIR}/icons/eye_gray.png",
        "red": f"{ASSETS_DIR}/icons/eye_red.png",
    }

    ethnicity_options = {
        "East Asian": "",
        "South Asian": "",
        "Southeast Asian": "",
        "Middle Eastern": "",
        "African": "",
        "European": "",
        "Latino": "",
        "Native American": "",
        "Oceanian": "",
    }

    body_type = {
        "underweight": f"{ASSETS_DIR}/icons/body_underweight_light.png",
        "athletic": f"{ASSETS_DIR}/icons/body_normal_light.png",
        "curvy": f"{ASSETS_DIR}/icons/body_overweight_light.png",
        "overweight": f"{ASSETS_DIR}/icons/body_obese_light.png",
        "obese": f"{ASSETS_DIR}/icons/body_morbidly_obese_light.png",
    }

    def __init__(self, profile: dict = None, name: str = None):
        super().__init__(expand=True, spacing=14, scroll=ft.ScrollMode.AUTO)
        self.profile = profile

        if name:
            name_value, name_enabled = name, False
        elif profile:
            name_value, name_enabled = profile["name"], True
        else:
            name_value, name_enabled = random.choice(self.male_names), True

        self.name_input = ft.TextField(
            value=name_value,
            disabled=not name_enabled,
            filled=True,
            bgcolor="#2C2C2C",
            border_radius=22,
            border_color="transparent",
            focused_border_color="#0D7377",
            content_padding=ft.Padding.only(left=16, right=16, top=10, bottom=10),
            height=44,
        )

        self.gender = RowSelector({"male": f"{ASSETS_DIR}/icons/male_light.png", "female": f"{ASSETS_DIR}/icons/female_light.png"})
        self.gender.on_selection_changed = self.on_gender_changed
        self.gender.select(profile["gender"] if profile else "male")

        self.age = RowSelector(self.male_ages)
        if profile:
            ages = [int(k) for k in self.male_ages]
            closest = min(ages, key=lambda x: abs(x - profile["age"]))
            self.age.select(str(closest))
        else:
            self.age.select("22")

        self.hair = RowSelector(self.hair_color, True, 7)
        self.hair.select(profile["hair_color"] if profile else None) if profile else self.hair.select_random()

        self.eye = RowSelector(self.eye_color, True, 7)
        self.eye.select(profile["eye_color"] if profile else None) if profile else self.eye.select_random()

        self.ethnicity = RowSelector(self.ethnicity_options, False, 3)
        self.ethnicity.select(profile["ethnicity"] if profile else None) if profile else self.ethnicity.select_random()

        self.body = RowSelector(self.body_type, True, 5)
        self.body.select(profile["body_type"] if profile else None) if profile else self.body.select_random()

        self.backstory = ft.TextField(
            hint_text="Type optional backstory here ...",
            multiline=True,
            min_lines=4,
            max_lines=8,
            value=profile["backstory"] if profile else "",
            filled=True,
            bgcolor="#2C2C2C",
            border_radius=16,
            border_color="transparent",
            focused_border_color="#0D7377",
            content_padding=16,
        )

        self.controls = [
            self._row("Name", self.name_input),
            self._row("Gender", self.gender),
            self._row("Age", self.age),
            self._row("Hair", self.hair),
            self._row("Eyes", self.eye),
            self._row("Ethnicity", self.ethnicity, top=True),
            self._row("Body Type", self.body),
            self._row("Backstory", self.backstory, top=True),
        ]

    def _row(self, label, control, top=False):
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text(label, color="#C8C8C8"),
                    width=LABEL_WIDTH,
                    padding=ft.Padding.only(top=12) if top else None,
                    alignment=ft.Alignment.TOP_LEFT if top else ft.Alignment.CENTER_LEFT,
                ),
                ft.Container(content=control, expand=True),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START if top else ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )

    def on_gender_changed(self, gender: str):
        if gender == "male":
            if not self.profile:
                self.name_input.value = random.choice(self.male_names)
                self.name_input.update()
            self.age.update_images(self.male_ages)
        else:
            if not self.profile:
                self.name_input.value = random.choice(self.female_names)
                self.name_input.update()
            self.age.update_images(self.female_ages)

    def get_values(self):
        return {
            "name": self.name_input.value or "",
            "gender": self.gender.get_selected(),
            "age": int(self.age.get_selected()),
            "hair_color": self.hair.get_selected(),
            "eye_color": self.eye.get_selected(),
            "ethnicity": self.ethnicity.get_selected(),
            "body_type": self.body.get_selected(),
            "backstory": self.backstory.value or "",
        }


class PersonalityPage(ft.Column):
    roles = [
        "Assistant", "Friend", "Partner", "Coach",
        "Therapist", "Mentor", "Rival", "Companion",
        "Motivator", "Teacher", "Muse", "Critic",
        "Cheerleader", "Pet",
    ]

    perosnality_attributes = {
        "Warmth": {"tags": ["cold", "warm"], "trait": ["cold", "distant", "reserved", "indifferent", "approachable", "friendly", "warm"]},
        "Formality": {"tags": ["casual", "formal"], "trait": ["informal", "casual", "semi-casual", "semi-formal", "very formal", "extremely formal", "excessively formal"]},
        "Energy": {"tags": ["calm", "energetic"], "trait": ["calm", "composed", "collected", "alert", "enthusiastic", "energetic", "passionate"]},
        "Humor": {"tags": ["serious", "funny"], "trait": ["serious", "thoughtful", "analytical", "humorous", "playful", "witty", "funny"]},
        "Directness": {"tags": ["gentle", "blunt"], "trait": ["gentle", "mild", "soft-spoken", "straightforward", "frank", "direct", "blunt"]},
        "Familiarity": {"tags": ["stranger", "best friend"], "trait": ["stranger", "acquaintance", "companion", "familiar", "friend", "close friend", "best friend"]},
        "Power": {"tags": ["submissive", "dominant"], "trait": ["submissive", "accommodating", "cooperative", "influential", "assertive", "confident", "dominant"]},
        "Initiative": {"tags": ["reactive", "active"], "trait": ["reactive", "responsive", "adaptable", "proactive", "initiative-taking", "pioneering", "active"]},
        "Honesty": {"tags": ["agreeable", "liar"], "trait": ["agreeable", "cooperative", "accommodating", "assertive", "confrontational", "challenging", "liar"]},
        "Intent": {"tags": ["manipulative", "benevolent"], "trait": ["manipulative", "exploitative", "self-serving", "prudent", "empathetic", "generous", "benevolent"]},
    }

    def __init__(self):
        super().__init__(expand=True, spacing=14, scroll=ft.ScrollMode.AUTO)
        self.perosnality_sliders = {}

        self.role = ft.Dropdown(
            options=[ft.DropdownOption(key=r, text=r) for r in self.roles],
            value="Assistant",
        )
        rows = [self._row("Role", self.role)]

        for name, item in self.perosnality_attributes.items():
            slider = LabeledSlider(
                left_text=item["tags"][0],
                right_text=item["tags"][1],
                range_min=0,
                range_max=len(item["trait"]) - 1,
                start_value=len(item["trait"]) / 2 - 1,
            )
            self.perosnality_sliders[name] = slider
            rows.append(self._row(name, slider))

        self.objective = ft.TextField(
            hint_text="Be helpful",
            multiline=True,
            min_lines=3,
            max_lines=6,
            value="Be helpful",
            filled=True,
            bgcolor="#2C2C2C",
            border_radius=16,
            border_color=ft.Colors.TRANSPARENT,
            focused_border_color="#0D7377",
            content_padding=ft.Padding.all(16),
        )
        self.sfw = RowSelector(
            {"SFW": f"{ASSETS_DIR}/icons/sfw_light.png", "NSFW": f"{ASSETS_DIR}/icons/nsfw_light.png"},
            False,
        )
        self.sfw.select("SFW")
        rows += [
            self._row("Objective", self.objective, top=True),
            self._row("NSFW", self.sfw),
        ]
        self.controls = rows

    def _row(self, label, control, top=False):
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text(label, color="#C8C8C8"),
                    width=LABEL_WIDTH,
                    padding=ft.Padding.only(top=12) if top else None,
                    alignment=ft.Alignment.TOP_LEFT if top else ft.Alignment.CENTER_LEFT,
                ),
                ft.Container(content=control, expand=True),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START if top else ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )

    def get_values(self):
        personality = ""
        for name, item in self.perosnality_attributes.items():
            value = int(self.perosnality_sliders[name].get_value())
            trait = item["trait"][value]
            if trait:
                personality = f"{personality}, {trait}" if personality else trait
        return {
            "role": self.role.value or "",
            "personality": personality,
            "objective": self.objective.value or "",
            "sfw": self.sfw.get_selected(),
        }


class ProgressPage(ft.Column):
    def __init__(self):
        super().__init__(
            expand=True,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.controls = [
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.ProgressRing(width=56, height=56, stroke_width=3),
                                ft.Text("Creating character", size=20, weight=ft.FontWeight.W_500),
                                ft.Text(
                                    "This may take a moment",
                                    size=13,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=16,
                        ),
                        padding=40,
                        border_radius=16,
                        bgcolor=ft.Colors.SURFACE_CONTAINER,
                    )
                ],
            )
        ]


class ProfileWizard(BasePage):
    selected_role = ""

    def __init__(self, navigator):
        super().__init__(navigator)
        self.user_profile_mode = False
        self.current_index = 0
        self.pages = []

        self.contact_header = ContactHeader(navigator, False)
        self.contact_header.on_go_back = self.on_go_back
        self.content_slot = ft.Container(expand=True)
        self.back_btn = ft.Button("...", on_click=self.prev_page, expand=True, visible=False, **STYLES["button"])
        self.next_btn = ft.Button("...", on_click=self.next_page, expand=True, **STYLES["button"])

        self.controls = [
            ft.Container(
                margin=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.contact_header,
                        self.content_slot,
                        ft.Row(controls=[self.back_btn, self.next_btn]),
                    ],
                ),
            )
        ]        

    def on_go_back(self, e=None):
        self.navigator("contacts")

    def add_page(self, widget):
        self.pages.append(widget)

    def clear_pages(self):
        self.pages.clear()
        self.current_index = 0

    def _show(self):
        if not self.pages:
            return
        self.content_slot.content = self.pages[self.current_index]
        self.content_slot.update()
        self.update_buttons()

    def _on_generation_timer(self):
        self.navigator("contacts")

    def next_page(self, e=None):
        if self.current_index < len(self.pages) - 2:
            self.current_index += 1
            self._show()
            return

        # means we are on the last page excluding the progress page
        profile = self.profile_page.get_values()
        if not self.user_profile_mode:
            Hub.generate({"generate_profile": {"profile": profile, "personality": self.personality_page.get_values()}})
            self.current_index += 1
            self._show()
        else:
            Hub.update_user_data({"profile": json.dumps(profile)})
            self.navigator("contacts")

    def prev_page(self, e=None):
        if self.current_index > 0:
            self.current_index -= 1
            self._show()

    def update_buttons(self):
        back = {0: (False, ""), 1: (True, "Back"), 2: (False, "")}
        next = {0: (True, "Next"), 1: (True, "Finish"), 2: (False, "")}
        self.back_btn.visible, self.back_btn.content = back.get(self.current_index, (False, ""))
        self.next_btn.visible, self.next_btn.content = next.get(self.current_index, (False, ""))
        self.update()

    def on_enter(self, **kwargs):
        self.user_profile_mode = kwargs.get("user_profile_mode", False)
        self.clear_pages()

        if self.user_profile_mode:
            data = Hub.get_user_data()
            name = Hub.get_user_name()
            profile = data["profile"] if data and "profile" in data else None
            self.profile_page = WizardProfilePage(profile=profile, name=name)
            self.add_page(self.profile_page)
        else:
            self.profile_page = WizardProfilePage()
            self.personality_page = PersonalityPage()
            self.progress_page = ProgressPage()
            self.add_page(self.profile_page)
            self.add_page(self.personality_page)
            self.add_page(self.progress_page)
            Hub.register_incomming_message(self.on_incomming_message)

        self._show()

    def on_leave(self):
        if not self.user_profile_mode:
            Hub.unregister_incomming_message(self.on_incomming_message)

    def on_incomming_message(self, msg: dict):
        try:
            if "new_contact" in msg:
                profile = self.profile_page.get_values()
                if profile["name"] == msg["new_contact"]["name"]:
                    self.navigator("contacts")
        except Exception as e:
            logger.error(f"failed to handle incomming message: {e}")            