import random
import flet as ft
from app.ui import theme

from app.utils import Hub
from app.audio import Text_To_Speech
from app.ui.wizzard_base import WizardPage, wizard_row, ASSETS_DIR
from app.ui.widgets import RowSelector, VoiceSelector
from app.common import get_logger, IMAGE_STYLE_OPTIONS, DEFAULT_IMAGE_STYLE, IMAGE_STYLE_ICONS

logger = get_logger()


class ContactWizardForm(ft.Column):
    """the simple new character form: name, gender, voice, backstory, style, persistent and nsfw"""

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

    def __init__(self):
        super().__init__(expand=True, spacing=14, scroll=ft.ScrollMode.AUTO)
        self.name_input = ft.TextField(
            value=random.choice(self.male_names),
            on_focus=self.on_name_focus,
            filled=True,
            bgcolor=theme.SURFACE_FIELD,
            border=theme.field_border(22, theme.ACCENT),
            content_padding=ft.Padding.only(left=16, right=16, top=10, bottom=10),
            height=44,
        )

        self.gender = RowSelector({"male": theme.icon("male"), "female": theme.icon("female")})
        self.gender.on_selection_changed = self.on_gender_changed
        self.gender.select("male")

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
            wizard_row("Name", self.name_input),
            wizard_row("Gender", self.gender),
            wizard_row("Voice", self.voice_selector),
            wizard_row("Backstory", self.backstory),
            wizard_row("Style", self.image_style),
            wizard_row(label = "Persistent", 
                       control = self.persistent_switch,
                       description = "Running as persistant Companion with it's own shedule."),
        ]
        if Hub.nsfw_allowed:
            self.controls.append(
                wizard_row(
                    label = "NSFW", 
                    control = self.nsfw_switch, 
                    description = "18+ experience"
                ))

    def get_voice(self):
        # kept out of get_values() because those values are json encoded and sent to the hub
        return self.voice_selector.get_voice()

    def on_name_focus(self, e=None):
        # a random name is only a suggestion: select it, so typing replaces it
        name = self.name_input.value or ""
        if name in self.male_names + self.female_names:
            self.name_input.selection = ft.TextSelection(base_offset=0, extent_offset=len(name))
            self.name_input.update()

    def on_gender_changed(self, gender: str):
        self.name_input.value = random.choice(self.male_names if gender == "male" else self.female_names)
        self.name_input.update()

    def get_values(self):
        return {
            "name": self.name_input.value or "",
            "gender": self.gender.get_selected(),
            "backstory": self.backstory.value or "",
            "sfw": "NSFW" if self.nsfw_switch.value else "SFW",
            "persistent": self.persistent_switch.value or False,
            "image_style": self.image_style.value or DEFAULT_IMAGE_STYLE,
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


class ContactWizard(WizardPage):
    """creates a new character: the hub generates it and sends new_contact when it is done"""

    def on_submit(self, e=None):
        profile = self.form.get_values()
        generate_profile = {"profile": profile}
        voice_id = self._store_voice(profile.get("gender", ""))
        if voice_id:
            generate_profile["voice_id"] = voice_id

        if not Hub.generate({"generate_profile": generate_profile}):
            return
        self._show(ProgressPage(), title="Creating your contact…")

    def _store_voice(self, gender: str) -> str | None:
        """stores the selected voice on the hub (blocking), returns its uuid or None"""
        voice = self.form.get_voice()
        if not voice:
            return None
        if "voice_id" in voice:
            return voice["voice_id"]
        if "predefined_id" in voice:
            return Hub.use_predefined_voice(voice["predefined_id"])
        return Hub.upload_voice(voice["bytes"], gender)

    def on_enter(self, **kwargs):
        self.form = ContactWizardForm()
        Hub.register_incomming_message(self.on_incomming_message)
        self._show(self.form, "Create", "Create a new contact", "Describe roughly who they are, the rest is generated. Later you can fine tune the character by editing it.")

    def on_leave(self):
        Hub.unregister_incomming_message(self.on_incomming_message)

    def on_incomming_message(self, msg: dict):
        try:
            if "new_contact" in msg:
                profile = self.form.get_values()
                if profile["name"] == msg["new_contact"]["name"]:
                    self.navigator("contacts")
        except Exception as e:
            logger.error(f"failed to handle incomming message: {e}")
