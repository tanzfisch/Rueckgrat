import json
from enum import Enum
import os
import random
import flet as ft
from app.ui import theme

from app.utils import Hub
from app.audio import Text_To_Speech
from app.ui import BasePage
from app.ui.widgets import Header, RowSelector, VoiceSelector
from app.common import get_logger, IMAGE_STYLE_OPTIONS, DEFAULT_IMAGE_STYLE, IMAGE_STYLE_ICONS

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

    # icon names, theme.icon() picks the light or dark drawing when the page is built
    _male_age_icons = {
        "18": "male_teen",
        "22": "male_20s",
        "27": "male_30s",
        "45": "male_40s",
        "60": "male_old",
    }

    _female_age_icons = {
        "18": "female_teen",
        "22": "female_20s",
        "27": "female_30s",
        "45": "female_40s",
        "60": "female_old",
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

    _body_type_icons = {
        "underweight": "body_underweight",
        "athletic": "body_normal",
        "curvy": "body_overweight",
        "overweight": "body_obese",
        "obese": "body_morbidly_obese",
    }

    def __init__(self, profile: dict = None, simple: bool = False, user_profile: bool = False):
        super().__init__(expand=True, spacing=14, scroll=ft.ScrollMode.AUTO)
        self.profile = profile
        self.simple = simple
        self.user_profile = user_profile
        self.male_ages = {k: theme.icon(v) for k, v in self._male_age_icons.items()}
        self.female_ages = {k: theme.icon(v) for k, v in self._female_age_icons.items()}
        self.body_type = {k: theme.icon(v) for k, v in self._body_type_icons.items()}

        if user_profile:
            name_value = ((profile or {}).get("name") or "").strip()
        elif profile:
            name_value = profile.get("name") or ""
        else:
            name_value = random.choice(self.male_names)

        self.name_input = ft.TextField(
            value=name_value,
            hint_text="Name of your character" if user_profile else None,
            on_change=self.on_name_changed,
            on_focus=self.on_name_focus,
            filled=True,
            bgcolor=theme.SURFACE_FIELD,
            border=theme.field_border(22, theme.ACCENT),
            content_padding=ft.Padding.only(left=16, right=16, top=10, bottom=10),
            height=44,
        )

        self.gender = RowSelector({"male": theme.icon("male"), "female": theme.icon("female")})
        self.gender.on_selection_changed = self.on_gender_changed
        self.gender.select(profile["gender"] if profile else "male")

        if simple:
            self._build_simple()
            return

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
            bgcolor=theme.SURFACE_FIELD,
            border=theme.field_border(16, theme.ACCENT),
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

    def _build_simple(self):
        self.backstory = ft.TextField(
            hint_text="Who are they? Include looks like hair colour, eyes, build, plus personality and what they want from you ...",
            multiline=True,
            min_lines=10,
            max_lines=20,
            value="",
            filled=True,
            bgcolor=theme.SURFACE_FIELD,
            border=theme.field_border(16, theme.ACCENT),
            content_padding=16,
        )
        self.nsfw_switch = ft.Switch(value=False, active_color=theme.ACCENT)
        self.persistent_switch = ft.Switch(value=False, active_color=theme.ACCENT)
        self.voice_selector = VoiceSelector(Hub.get_predefined_voices(), on_play_sample=Text_To_Speech.play_voice_sample)

        self.image_style = ft.Dropdown(
            options=[
                ft.DropdownOption(
                    key=style,
                    text=f"{style.replace('_', ' ')}: {description}",
                    leading_icon=ft.Image(
                        src=IMAGE_STYLE_ICONS[style], width=40, height=40, fit=ft.BoxFit.COVER, border_radius=4,
                        error_content=ft.Container(width=32, height=32),  # missing file: keep the space, show nothing
                    ),
                )
                for style, description in IMAGE_STYLE_OPTIONS.items()
            ],
            value=DEFAULT_IMAGE_STYLE,
            expand=True,
            filled=True,
            fill_color=theme.SURFACE_FIELD,
        )

        self.controls = [
            self._row("Name", self.name_input),
            self._row("Gender", self.gender),
            self._row("Voice", self.voice_selector),
            self._row("Backstory", self.backstory),
            self._row("Style", self.image_style),
            self._row(label = "Persistent", 
                      control = self.persistent_switch,
                      description = "Running as persistant Companion with it's own shedule."),
        ]
        if Hub.nsfw_allowed:
            self.controls.append(
                self._row(
                    label = "NSFW", 
                    control = self.nsfw_switch, 
                    description = "18+ experience"
                ))

    def _row(self, label, control, description: str = None):
        row = ft.Row(
            [
                ft.Container(
                    content=ft.Text(label, color=theme.TEXT_LABEL),
                    width=LABEL_WIDTH,
                    padding=ft.Padding.only(top=12),
                    alignment=ft.Alignment.TOP_LEFT,
                ),
                ft.Container(
                    content=control, 
                    expand=False if description else True,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=12,
        )

        if description:
            row.controls.append(ft.Container(
                                content=ft.Text(description, color=theme.TEXT_LABEL),
                                expand=True,
                                alignment=ft.Alignment.TOP_LEFT,
                            ))

        return row

    def get_voice(self):
        # kept out of get_values() because those values are json encoded and sent to the hub
        return self.voice_selector.get_voice()

    def on_name_focus(self, e=None):
        # a random name is only a suggestion: select it, so typing replaces it
        name = self.name_input.value or ""
        if self._randomize_name() and name in self.male_names + self.female_names:
            self.name_input.selection = ft.TextSelection(base_offset=0, extent_offset=len(name))
            self.name_input.update()

    def on_name_changed(self, e=None):
        # clear the validation message once the user starts typing
        if self.name_input.error:
            self.name_input.error = None
            self.name_input.update()

    def validate_name(self) -> bool:
        if (self.name_input.value or "").strip():
            return True
        self.name_input.error = "Please enter a name for your character"
        self.name_input.update()
        return False

    def _randomize_name(self) -> bool:
        # random names only for a brand new character, never for the user's own one
        return not self.profile and not self.user_profile

    def on_gender_changed(self, gender: str):
        if gender == "male":
            if self._randomize_name():
                self.name_input.value = random.choice(self.male_names)
                self.name_input.update()
            if not self.simple:
                self.age.update_images(self.male_ages)
        else:
            if self._randomize_name():
                self.name_input.value = random.choice(self.female_names)
                self.name_input.update()
            if not self.simple:
                self.age.update_images(self.female_ages)

    def get_values(self):
        if self.simple:
            return {
                "name": self.name_input.value or "",
                "gender": self.gender.get_selected(),
                "backstory": self.backstory.value or "",
                "sfw": "NSFW" if self.nsfw_switch.value else "SFW",
                "persistent": self.persistent_switch.value or False,
                "image_style": self.image_style.value or DEFAULT_IMAGE_STYLE,
            }
        return {
            "name": (self.name_input.value or "").strip(),
            "gender": self.gender.get_selected(),
            "age": int(self.age.get_selected()),
            "hair_color": self.hair.get_selected(),
            "eye_color": self.eye.get_selected(),
            "ethnicity": self.ethnicity.get_selected(),
            "body_type": self.body.get_selected(),
            "backstory": self.backstory.value or "",
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
                                ft.Image(src=f"{ASSETS_DIR}/icons/loading.gif", width=56, height=56, fit=ft.BoxFit.CONTAIN),
                                ft.Text("Creating character", size=20, weight=ft.FontWeight.W_500),
                                ft.Text(
                                    "This may take a moment",
                                    size=13,
                                    color=theme.TEXT_VARIANT,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=16,
                        ),
                        padding=40,
                        border_radius=16,
                        bgcolor=theme.CARD,
                    )
                ],
            )
        ]




class ProfileWizzardMode(Enum):
    UserSetup = 1
    UserChange = 2
    AIContact = 3

class ProfileWizard(BasePage):
    """one form: the simple new character form, or the full form for the user's own profile"""

    def __init__(self, navigator):
        super().__init__(navigator)
        self.user_profile_mode = ProfileWizzardMode.AIContact

        self.header = Header(navigator, False)
        self.header.on_go_back = self.on_go_back
        self.content_slot = ft.Container(expand=True)
        self.submit_btn = ft.Button("...", on_click=self.on_submit, expand=True, **theme.STYLES["button"])
        self.cancel_btn = ft.Button("Cancel", on_click=self.on_go_back, expand=True, visible=False, **theme.STYLES["button"])

        self.controls = [
            ft.Container(
                margin=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.header,
                        self.content_slot,
                        ft.Row(controls=[self.cancel_btn, self.submit_btn]),
                    ],
                ),
            )
        ]

    def on_go_back(self, e=None):
        # the first setup after login (Skip) carries on to the contacts, the others go back to where they were opened
        if self.user_profile_mode == ProfileWizzardMode.UserSetup or not self.navigator.back():
            self.navigator("contacts")

    def _show(self, content, button_text: str = None):
        # button_text None hides the button, e.g. while the character is generated
        self.content_slot.content = content
        self.submit_btn.visible = button_text is not None
        self.submit_btn.content = button_text or ""
        self.cancel_btn.visible = self.user_profile_mode != ProfileWizzardMode.AIContact and button_text is not None
        self.update()

    def on_submit(self, e=None):
        if self.user_profile_mode != ProfileWizzardMode.AIContact and not self.profile_page.validate_name():
            return
        
        profile = self.profile_page.get_values()
        if self.user_profile_mode != ProfileWizzardMode.AIContact:
            Hub.update_user_data({"profile": json.dumps(profile)})
            self.on_go_back()
            return

        generate_profile = {"profile": profile}
        voice_id = self._store_voice(profile.get("gender", ""))
        if voice_id:
            generate_profile["voice_id"] = voice_id

        if not Hub.generate({"generate_profile": generate_profile}):
            return
        self._show(ProgressPage())

    def _store_voice(self, gender: str) -> str | None:
        """stores the selected voice on the hub (blocking), returns its uuid or None"""
        voice = self.profile_page.get_voice()
        if not voice:
            return None
        if "voice_id" in voice:
            return voice["voice_id"]
        if "predefined_id" in voice:
            return Hub.use_predefined_voice(voice["predefined_id"])
        return Hub.upload_voice(voice["bytes"], gender)

    def on_enter(self, **kwargs):
        self.user_profile_mode = kwargs.get("user_profile_mode", ProfileWizzardMode.AIContact)

        if self.user_profile_mode != ProfileWizzardMode.AIContact:
            data = Hub.get_user_data()
            profile = data["profile"] if data and "profile" in data else None
            self.profile_page = WizardProfilePage(profile=profile, user_profile=True)

            if self.user_profile_mode == ProfileWizzardMode.UserSetup:
                self.cancel_btn.content = "Skip"

            self._show(self.profile_page, "Save")
        else:
            self.profile_page = WizardProfilePage(simple=True)
            Hub.register_incomming_message(self.on_incomming_message)
            self._show(self.profile_page, "Create")

    def on_leave(self):
        if self.user_profile_mode == ProfileWizzardMode.AIContact:
            Hub.unregister_incomming_message(self.on_incomming_message)

    def on_incomming_message(self, msg: dict):
        try:
            if "new_contact" in msg:
                profile = self.profile_page.get_values()
                if profile["name"] == msg["new_contact"]["name"]:
                    self.navigator("contacts")
        except Exception as e:
            logger.error(f"failed to handle incomming message: {e}")
