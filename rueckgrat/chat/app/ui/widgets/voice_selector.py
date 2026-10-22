import io
import wave
import flet as ft

from app.utils import Hub
from app.audio import Text_To_Speech
from app.ui.widgets.bubbles import OneLineBubble
from app.ui.widgets.message_box import MessageBox
from app.common import get_logger

logger = get_logger()


class VoiceSelector(ft.Column):
    """optional reference voice for tts: a predefined voice from the hub or an own wav, kept in local state only"""

    # keys of the two extra entries in the voice select, predefined voices use their id as key
    NO_VOICE_KEY = "__no_voice__"
    UPLOAD_VOICE_KEY = "__upload_voice__"
    # only present when editing a contact that already has a voice, its value is the stored hub uuid
    CURRENT_VOICE_KEY = "__current_voice__"

    def __init__(self):
        super().__init__(spacing=8)
        self.voice_file_name = None
        self.voice_file_path = None
        self.voice_file_bytes = None
        self.file_picker = None
        self.current_voice_id = ""

        self.predefined_voices = Hub.get_predefined_voices()

        self.voice_select = ft.Dropdown(
            options=self._build_options(),
            value=self.NO_VOICE_KEY,
            on_select=self.on_voice_selected,
            expand=True,
            filled=True,
            fill_color="#2C2C2C",
            menu_height=400,
        )

        self.voice_upload_btn = OneLineBubble("upload voice (wav)", on_clicked=lambda text, data: self.page.run_task(self.on_pick_voice), height=48, expand=True)
        self.voice_name_text = ft.Text("", color="#C8C8C8", visible=False)
        self.voice_clear_btn = ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Remove voice", on_click=self.on_clear_voice, visible=False)
        # only shown while "upload own voice" is selected
        self.voice_upload_row = ft.Row([self.voice_upload_btn, self.voice_name_text, self.voice_clear_btn], spacing=8, visible=False)
        self.controls = [ft.Row([self.voice_select]), self.voice_upload_row]

    @staticmethod
    def _voice_text(voice: dict) -> str:
        # the visible text is gender, language, description and name, the id is only the key
        parts = [voice.get("gender", ""), voice.get("language", ""), voice.get("description", ""), voice["name"]]
        return ", ".join(p for p in parts if p)

    def _build_options(self, current_text: str = "") -> list:
        options = [ft.DropdownOption(key=self.NO_VOICE_KEY, text="default voice")]
        if current_text:
            # a contact voice that could not be matched to a predefined one, so there are no details to show
            options.append(ft.DropdownOption(key=self.CURRENT_VOICE_KEY, text=current_text))
        for voice in self.predefined_voices:
            options.append(ft.DropdownOption(key=voice["id"], text=self._voice_text(voice), trailing_icon=self._sample_button(voice["id"])))
        options.append(ft.DropdownOption(key=self.UPLOAD_VOICE_KEY, text="upload own voice (wav)…"))
        return options

    @staticmethod
    def _sample_button(predefined_id: str) -> ft.IconButton:
        # the button takes the tap, so the option is not selected and the menu stays open
        return ft.IconButton(
            icon=ft.Icons.PLAY_ARROW,
            tooltip="Play sample",
            on_click=lambda e: Text_To_Speech.play_voice_sample(predefined_id),
        )

    def set_current_voice(self, voice_id: str):
        """pre-selects the voice a contact already has, an empty id resets the select to "default voice" """
        self.current_voice_id = voice_id or ""
        if not self.current_voice_id:
            self.voice_select.options = self._build_options()
            self.voice_select.value = self.NO_VOICE_KEY
        else:
            # fetch again, the user may have stored more predefined voices since this widget was built
            self.predefined_voices = Hub.get_predefined_voices()
            predefined = next((v for v in self.predefined_voices if v.get("voice_id") == self.current_voice_id), None)
            if predefined:
                # select the predefined entry itself, saving maps it back to the same uuid on the hub
                self.voice_select.options = self._build_options()
                self.voice_select.value = predefined["id"]
            else:
                # only call it uploaded if the hub sent the mapping (voice_id key), an older hub can't tell
                hub_can_match = any("voice_id" in v for v in self.predefined_voices)
                text = "own uploaded voice (current)" if hub_can_match else "current voice"
                self.voice_select.options = self._build_options(current_text=text)
                self.voice_select.value = self.CURRENT_VOICE_KEY
        self.voice_upload_row.visible = False
        self.on_clear_voice(update=False)

    def on_voice_selected(self, e=None):
        self.voice_upload_row.visible = self.voice_select.value == self.UPLOAD_VOICE_KEY
        self.update()

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

    def on_clear_voice(self, e=None, update: bool = True):
        self.voice_file_name = None
        self.voice_file_path = None
        self.voice_file_bytes = None
        self.voice_name_text.visible = False
        self.voice_clear_btn.visible = False
        if update:
            self.update()

    def get_voice(self):
        # None, {"voice_id": ...} (unchanged current voice), {"predefined_id": ...} or {"name", "path", "bytes"} of an uploaded wav
        selected = self.voice_select.value
        if selected == self.CURRENT_VOICE_KEY:
            return {"voice_id": self.current_voice_id}
        if selected == self.UPLOAD_VOICE_KEY:
            if not self.voice_file_bytes:
                return None
            return {"name": self.voice_file_name, "path": self.voice_file_path, "bytes": self.voice_file_bytes}
        if selected and selected != self.NO_VOICE_KEY:
            return {"predefined_id": selected}
        return None

    def store_on_hub(self, gender: str = "") -> str | None:
        """sends the selection to the hub (blocking), returns the uuid of the stored voice or None"""
        voice = self.get_voice()
        if not voice:
            return None
        if "voice_id" in voice:
            return voice["voice_id"]
        if "predefined_id" in voice:
            return Hub.use_predefined_voice(voice["predefined_id"])
        return Hub.upload_voice(voice["bytes"], gender)
