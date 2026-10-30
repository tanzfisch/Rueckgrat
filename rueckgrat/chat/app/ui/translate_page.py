import asyncio
import uuid
import flet as ft
from app.ui.theme import STYLES, RADIUS, TEAL_BRIGHT

from app.ui import BasePage
from app.ui.widgets import ChatBubble, Header, LanguagePicker, flag_text
from app.audio import Text_To_Speech
from app.utils import Hub, AudioStreamer, RueckgratConfig
from app.common import get_logger
from app.common.languages import LANGUAGES, language_name

logger = get_logger()


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


class MessageRow(ft.Row):
    """one message in a half, with its play button. speech only plays when the button is pressed"""

    def __init__(self, text: str, own: bool, language: str, on_play, speakable: bool = True):
        self.language = language
        self.bubble = ChatBubble("user" if own else "assistant", "")
        self.play_btn = ft.IconButton(icon=ft.Icons.PLAY_ARROW, icon_size=20, on_click=lambda e: on_play(self))
        slot = ft.Container(content=self.bubble, expand=85, **STYLES["chat_user" if own else "chat_assistant"])
        spacer = ft.Container(expand=15)
        super().__init__(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[spacer, self.play_btn, slot] if own else [slot, self.play_btn, spacer],
        )
        self.set_text(text, speakable)

    @property
    def text(self) -> str:
        return self.bubble.raw_content

    def set_text(self, text: str, speakable: bool = True):
        self.bubble.clear_content()
        self.bubble.append_content(text)
        has_tts = LANGUAGES[self.language]["tts"]
        self.play_btn.disabled = not (speakable and has_tts)
        self.play_btn.tooltip = None if has_tts else f"no speech output for {language_name(self.language)}"
        _update(self)


class TranslateHalf(ft.Container):
    """the half of one person: their messages (teal) and the translations of the other half's (grey),
    an input bar with the flag of their language, the mic and send"""

    def __init__(self, owner: "TranslatePage", language: str):
        self.owner = owner
        self.language = language
        self.history = ft.ListView(expand=True, spacing=10, padding=0, auto_scroll=True)
        enter_sends = RueckgratConfig().enter_sends   # same user setting as the chat, else ctrl+enter sends
        self.input_box = ft.TextField(
            hint_text="Type here...",
            multiline=True,
            shift_enter=enter_sends,
            on_submit=(lambda e: owner.send(self)) if enter_sends else None,
            min_lines=1,
            max_lines=4,
            expand=True,
            border=ft.NoInputBorder(),
            on_focus=lambda e: owner.set_active(self),
            text_style=ft.TextStyle(font_family="DejaVu Sans", font_family_fallback=["Noto Color Emoji"]),
        )
        self.flag_btn = ft.IconButton(icon=flag_text(language), on_click=lambda e: owner.page.run_task(owner.pick_language, self))
        self.mic_btn = ft.IconButton(icon=ft.Icons.MIC_OFF, icon_size=24, on_click=lambda e: owner.toggle_mic(self))
        self.send_btn = ft.IconButton(icon=ft.Icons.SEND, icon_size=24, on_click=lambda e: owner.send(self))
        bar = ft.Container(
            border_radius=20,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            padding=ft.Padding(left=8, top=8, right=8, bottom=8),
            content=ft.Column(
                spacing=0,
                controls=[
                    self.input_box,
                    ft.Row(controls=[ft.Container(expand=True), self.flag_btn, self.mic_btn, self.send_btn]),
                ],
            ),
        )
        super().__init__(
            expand=True,
            padding=8,
            border_radius=RADIUS,
            on_click=lambda e: owner.set_active(self),
            content=ft.Column(expand=True, controls=[self.history, bar]),
        )

    def set_active(self, active: bool):
        self.border = ft.Border.all(2, TEAL_BRIGHT) if active else None
        _update(self)

    def set_language(self, code: str):
        self.language = code
        self.flag_btn.icon = flag_text(code)
        _update(self.flag_btn)

    def set_mic(self, on: bool):
        self.mic_btn.icon = ft.Icons.MIC if on else ft.Icons.MIC_OFF
        _update(self.mic_btn)

    def add_message(self, text: str, own: bool, speakable: bool = True) -> MessageRow:
        row = MessageRow(text, own, self.language, self.owner.play, speakable)
        self.history.controls.append(row)
        _update(self.history)
        return row


class TranslatePage(BasePage):
    """translator for two people sharing one phone: each uses their own half and language,
    a message sent in one half shows up translated in the other. nothing is stored"""

    def __init__(self, navigator):
        super().__init__(navigator)
        self.header = Header(navigator, selected_contact=False)
        self.header.on_go_back = self.on_go_back
        # not top/bottom: those are flet position properties of the page (a Column), a control there breaks the render
        self.upper = TranslateHalf(self, "en")
        self.lower = TranslateHalf(self, "de")
        self.active = None
        self._pending: dict[str, MessageRow] = {}   # request id -> the row in the other half waiting for the translation
        self.audio_streamer = None
        self._mic_half = None
        self._playing = None                         # row whose speech was started last
        self.set_active(self.upper)

        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(expand=True, controls=[self.header, self.upper, self.lower]),
            ),
        ]

    def did_mount(self):
        self.page.on_keyboard_event = self._on_keyboard

    def _on_keyboard(self, e: ft.KeyboardEvent):
        if e.key == "Enter" and e.ctrl and self.active and not self.active.input_box.shift_enter:   # enter sends: on_submit sends
            self.send(self.active)

    def on_go_back(self, e=None):
        self.navigator.back()

    def on_enter(self, **kwargs):
        Hub.register_incomming_message(self.on_incomming_message)

    def on_leave(self):
        Hub.unregister_incomming_message(self.on_incomming_message)
        if self._playing:
            Text_To_Speech.kill_current_speech()
        if self.audio_streamer:
            self.page.run_task(self._stop_mic)

    def other(self, half: TranslateHalf) -> TranslateHalf:
        return self.lower if half is self.upper else self.upper

    def set_active(self, half: TranslateHalf):
        if half is self.active:
            return
        self.active = half
        for h in (self.upper, self.lower):
            h.set_active(h is half)

    async def pick_language(self, half: TranslateHalf):
        self.set_active(half)
        code = await LanguagePicker.open(self.page, half.language)
        if not code or code == half.language:
            return
        half.set_language(code)
        if self._mic_half is half:
            await self._switch_mic(half)  # the stt language changed

    def send(self, half: TranslateHalf):
        self.set_active(half)
        text = (half.input_box.value or "").strip()
        if not text:
            return
        other = self.other(half)
        request_id = uuid.uuid4().hex
        if not Hub.translate(half.language, other.language, text, request_id):
            return  # not connected, the connection banner shows it
        half.input_box.value = ""
        _update(half.input_box)
        half.add_message(text, own=True)
        self._pending[request_id] = other.add_message("…", own=False, speakable=False)

    def on_incomming_message(self, message: dict):
        if "translate" not in message:
            return
        translate = message["translate"]
        row = self._pending.pop(translate.get("request_id"), None)
        if row is None:
            return  # not from this page
        if translate.get("translation"):
            row.set_text(translate["translation"])
        else:
            row.set_text(f"⚠ {translate.get('error', 'translation failed')}", speakable=False)

    def play(self, row: MessageRow):
        """starts the speech of a row, pressing it again while it plays stops it"""
        if self._playing is row and Text_To_Speech.state != "idle":
            Text_To_Speech.kill_current_speech()
            return
        Text_To_Speech.speak(text=row.text, language=row.language)
        self._playing = row
        self.page.run_task(self._follow_playback, row)

    async def _follow_playback(self, row: MessageRow):
        """the row's play button shows stop while its speech is generated or played"""
        row.play_btn.icon = ft.Icons.STOP
        _update(row.play_btn)
        while self._playing is row and Text_To_Speech.state != "idle":
            await asyncio.sleep(0.2)
        row.play_btn.icon = ft.Icons.PLAY_ARROW
        _update(row.play_btn)

    def toggle_mic(self, half: TranslateHalf):
        """one mic at a time: it listens in the language of its half and sends what was said from there"""
        self.set_active(half)
        self.page.run_task(self._switch_mic, None if self._mic_half is half else half)

    async def _switch_mic(self, half: TranslateHalf | None):
        await self._stop_mic()
        if half is None:
            return
        self._mic_half = half
        half.set_mic(True)
        self.audio_streamer = AudioStreamer(
            uri=Hub.uri.replace("/ws", "/ws/audio"),
            token=Hub.access_token,
            cert=Hub.server_cert,
            on_message=lambda payload: self.page.run_task(self._handle_audio_payload, half, payload),
            language=half.language,
        )
        try:
            self.audio_streamer.attach(self.page)
            await self.audio_streamer.start()
        except Exception as e:
            logger.error(f"failed to start the mic: {e!r}")
            await self._stop_mic()

    async def _stop_mic(self):
        if self._mic_half:
            self._mic_half.set_mic(False)
            self._mic_half = None
        if self.audio_streamer:
            await self.audio_streamer.stop()
            self.audio_streamer = None

    async def _handle_audio_payload(self, half: TranslateHalf, payload: dict):
        if half is not self._mic_half:
            return  # the mic was switched to the other half meanwhile
        kind = payload.get("type")
        if kind == "mic.off":
            await self._stop_mic()
            return
        text = (payload.get("text") or "").strip()
        if not text:
            return
        half.input_box.value = text
        _update(half.input_box)
        if kind == "final":
            self.send(half)
