import io
import json
import os
import wave
import random
import flet as ft
from app.ui.theme import STYLES

from app.utils import Hub
from app.ui import BasePage
from app.ui.widgets import ContactHeader, RowSelector, OneLineBubble, MessageBox
from app.common import get_logger

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

    def __init__(self, profile: dict = None, name: str = None, simple: bool = False):
        super().__init__(expand=True, spacing=14, scroll=ft.ScrollMode.AUTO)
        self.profile = profile
        # simple: new character page with name, gender, voice, backstory and sfw only, the hub infers the rest
        self.simple = simple

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

    def _build_simple(self):
        self.backstory = ft.TextField(
            hint_text="Who are they? Include looks like hair colour, eyes, build, plus personality and what they want from you ...",
            multiline=True,
            min_lines=10,
            max_lines=20,
            value="",
            filled=True,
            bgcolor="#2C2C2C",
            border_radius=16,
            border_color="transparent",
            focused_border_color="#0D7377",
            content_padding=16,
        )
        self.sfw_switch = ft.Switch(value=True, active_color="#0D7377")

        self.controls = [
            self._row("Name", self.name_input),
            self._row("Gender", self.gender),
            self._row("Voice", self._build_voice_row()),
            self._row("Backstory", self.backstory, top=True),
            self._row("SFW", self.sfw_switch),
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

    def _build_voice_row(self):
        # optional reference voice (wav) for tts, kept in local state only
        self.voice_file_name = None
        self.voice_file_path = None
        self.voice_file_bytes = None
        self.file_picker = None

        self.voice_upload_btn = OneLineBubble("upload voice (wav)", on_clicked=lambda text, data: self.page.run_task(self.on_pick_voice), height=48, expand=True)
        self.voice_name_text = ft.Text("", color="#C8C8C8", visible=False)
        self.voice_clear_btn = ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Remove voice", on_click=self.on_clear_voice, visible=False)
        return ft.Row([self.voice_upload_btn, self.voice_name_text, self.voice_clear_btn], spacing=8)

    @staticmethod
    def _validate_wav(data: bytes) -> str | None:
        # returns an error message, or None if the wav looks usable
        try:
            with wave.open(io.BytesIO(data), "rb") as w:
                if w.getnchannels() < 1:
                    return "WAV has no channels"
                if w.getnframes() <= 0:
                    return "WAV contains no audio"
                if not 8000 <= w.getframerate() <= 192000:
                    return f"unsupported sample rate {w.getframerate()} Hz"
                if w.getsampwidth() not in (1, 2, 3, 4):
                    return f"unsupported sample width {w.getsampwidth()} bytes"
        except Exception as e:
            return f"not a valid WAV file ({e})"
        return None

    async def on_pick_voice(self, e=None):
        # FilePicker is a service in flet 1.0, create it lazily inside the event handler so a page context exists
        if self.file_picker is None:
            self.file_picker = ft.FilePicker()
        files = await self.file_picker.pick_files(
            dialog_title="Select voice sample",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["wav"],
            allow_multiple=False,
            with_data=True,  # on android/web path is None, so we need the bytes
        )
        if not files:
            return
        file = files[0]
        data = file.bytes
        if data is None and file.path:
            with open(file.path, "rb") as f:
                data = f.read()

        error = self._validate_wav(data) if data else "could not read file"
        if error:
            logger.warning(f"rejected voice file {file.name}: {error}")
            MessageBox.error(self.page, f"File \"{file.name}\" can not be used as voice. Error: {error}", title="Invalid voice file")
            return

        self.voice_file_name = file.name
        self.voice_file_path = file.path
        self.voice_file_bytes = data
        self.voice_name_text.value = file.name
        self.voice_name_text.visible = True
        self.voice_clear_btn.visible = True
        self.update()

    def on_clear_voice(self, e=None):
        self.voice_file_name = None
        self.voice_file_path = None
        self.voice_file_bytes = None
        self.voice_name_text.visible = False
        self.voice_clear_btn.visible = False
        self.update()

    def get_voice(self):
        # kept out of get_values() because those values are json encoded and sent to the hub
        if not self.voice_file_bytes:
            return None
        return {"name": self.voice_file_name, "path": self.voice_file_path, "bytes": self.voice_file_bytes}

    def on_gender_changed(self, gender: str):
        if gender == "male":
            if not self.profile:
                self.name_input.value = random.choice(self.male_names)
                self.name_input.update()
            if not self.simple:
                self.age.update_images(self.male_ages)
        else:
            if not self.profile:
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
                "sfw": "SFW" if self.sfw_switch.value else "NSFW",
            }
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
    """one form: the simple new character form, or the full form for the user's own profile"""

    def __init__(self, navigator):
        super().__init__(navigator)
        self.user_profile_mode = False

        self.contact_header = ContactHeader(navigator, False)
        self.contact_header.on_go_back = self.on_go_back
        self.content_slot = ft.Container(expand=True)
        self.submit_btn = ft.Button("...", on_click=self.on_submit, expand=True, **STYLES["button"])
        # only shown when the user edits their own profile, discards the changes
        self.cancel_btn = ft.Button("Cancel", on_click=self.on_go_back, expand=True, visible=False, **STYLES["button"])

        self.controls = [
            ft.Container(
                margin=20,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.contact_header,
                        self.content_slot,
                        ft.Row(controls=[self.cancel_btn, self.submit_btn]),
                    ],
                ),
            )
        ]

    def on_go_back(self, e=None):
        self.navigator("contacts")

    def _show(self, content, button_text: str = None):
        # button_text None hides the button, e.g. while the character is generated
        self.content_slot.content = content
        self.submit_btn.visible = button_text is not None
        self.submit_btn.content = button_text or ""
        self.cancel_btn.visible = self.user_profile_mode and button_text is not None
        self.update()

    def on_submit(self, e=None):
        profile = self.profile_page.get_values()
        if self.user_profile_mode:
            Hub.update_user_data({"profile": json.dumps(profile)})
            self.navigator("contacts")
            return

        # the hub infers role, personality and looks from the backstory
        generate_profile = {"profile": profile}
        voice = self.profile_page.get_voice()
        if voice:
            # blocking upload, the hub answers with the uuid of the stored voice
            voice_id = Hub.upload_voice(voice["bytes"], profile.get("gender", ""))
            if voice_id:
                generate_profile["voice_id"] = voice_id

        Hub.generate({"generate_profile": generate_profile})
        self._show(ProgressPage())

    def on_enter(self, **kwargs):
        self.user_profile_mode = kwargs.get("user_profile_mode", False)

        if self.user_profile_mode:
            data = Hub.get_user_data()
            name = Hub.get_user_name()
            profile = data["profile"] if data and "profile" in data else None
            self.profile_page = WizardProfilePage(profile=profile, name=name)
            self._show(self.profile_page, "Save")
        else:
            self.profile_page = WizardProfilePage(simple=True)
            Hub.register_incomming_message(self.on_incomming_message)
            self._show(self.profile_page, "Create")

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
