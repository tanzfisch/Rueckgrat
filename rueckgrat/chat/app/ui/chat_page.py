import asyncio
import re
import flet as ft
from app.ui.theme import STYLES
from pathlib import Path

from app.ui import BasePage
from app.ui.widgets import ChatBubble, ContactHeader, EmojiPicker, StatusWidget
from app.audio import Text_To_Speech
from app.utils import Hub, Contact, Paths, AudioStreamer
from app.common import get_logger, Utils

logger = get_logger()


class ChatPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)
        self.contact_id = None
        self.conversation_id = None
        self.contact = None
        self.audio_streamer = None
        self.delta_buffer = ""
        self._stream_gen = 0
        self.replay_content = ""

        self.contact_header = ContactHeader(navigator)
        self.contact_header.on_go_back = self.on_go_back

        self.history = ft.ListView(expand=True, spacing=10, padding=8, auto_scroll=True)
        self.status_widget = StatusWidget()
        self.stream_bubble = ChatBubble("assistant", "", None)
        self.stream_bubble.visible = False

        self._input_focused = False
        self.input_box = ft.TextField(
            hint_text="Type here...",
            multiline=True,
            min_lines=1,
            max_lines=8,
            expand=True,
            on_focus=lambda e: setattr(self, "_input_focused", True),
            on_blur=lambda e: setattr(self, "_input_focused", False),
            text_style=ft.TextStyle(
                font_family="DejaVu Sans",
                font_family_fallback=["Noto Color Emoji"],
            ),            
        )

        self.mic_btn = ft.IconButton(
            icon=ft.Icons.MIC_OFF,
            icon_size=24,
            selected=False,
            on_click=self.on_mic_toggle,
        )

        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(
                    expand=True,
                    controls=[
                        self.contact_header,
                        self.history,
                        ft.Row(
                            vertical_alignment=ft.CrossAxisAlignment.END,
                            controls=[
                                ft.PopupMenuButton(
                                    icon=ft.Icons.MENU,
                                    items=[ft.PopupMenuItem(content="... replay", on_click=lambda e: self.replay())],
                                ),
                                self.input_box,
                                ft.IconButton(icon=ft.Icons.EMOJI_EMOTIONS, icon_size=24, on_click=self.open_emoji_picker),
                                self.mic_btn,
                                ft.IconButton(icon=ft.Icons.SEND, icon_size=24, on_click=lambda e: self.send_message()),
                            ],
                        ),
                    ],
                ),
            ),
        ]

    def did_mount(self):
        self.page.on_keyboard_event = self._on_keyboard

    def _on_keyboard(self, e: ft.KeyboardEvent):
        if e.key == "Enter" and e.ctrl and self._input_focused:
            self.send_message()

    async def open_emoji_picker(self, e=None):
        result = await EmojiPicker.open(self.page)
        if result:
            self.input_box.value = (self.input_box.value or "") + result
            self.input_box.update()

    def on_go_back(self, e=None):
        self.navigator("conversations", contact_id=self.contact_id)

    def clear_history(self):
        self.status_widget.clear_status()
        self.stream_bubble.clear_content()
        self.stream_bubble.visible = False
        self.history.controls = [
            ft.Row(controls=[self.status_widget]),
            ft.Row(controls=[self.stream_bubble]),
        ]
        self.history.update()

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        self.conversation_id = kwargs.get("conversation_id")
        self.contact = Contact(Hub.get_contact(self.contact_id))
        self.contact_header.set_contact(self.contact)
        self.clear_history()

        for message in Hub.get_messages(self.conversation_id):
            attachments = Hub.get_attachments(message["id"])
            if attachments:
                image_path = self._get_image(attachments[0]["file_name"])
                self._append_history(message["role"], message["content"], image_path)
            else:
                self._append_history(message["role"], message["content"])

        default_piper = (
            "en_US-hfc_male-medium"
            if self.contact.get_gender() == "male"
            else "en_US-libritts_r-medium"
        )
        self.piper_model = self.contact.get_voice_model() or default_piper
        self.temperature = float(self.contact.get_llm_temperature())
        Hub.register_incomming_message(self.on_incomming_message)

        if self.page:
            self.page.run_task(self.input_box.focus)

    def on_leave(self):
        if self.page:
            self.page.run_task(self._stop_mic)
        Hub.unregister_incomming_message(self.on_incomming_message)

    def on_mic_toggle(self, e=None):
        self.mic_btn.selected = not self.mic_btn.selected
        if self.mic_btn.selected:
            self.mic_btn.icon = ft.Icons.MIC
            if self.page:
                self.page.run_task(self._start_mic)
        else:
            self.mic_btn.icon = ft.Icons.MIC_OFF
            if self.page:
                self.page.run_task(self._stop_mic)
        self.mic_btn.update()

    async def _start_mic(self):
        await self._stop_mic()
        self.audio_streamer = AudioStreamer(
            uri=Hub.uri.replace("/ws", "/ws/audio"),
            token=Hub.access_token,
            cert=Hub.server_cert,
            on_message=self._on_audio_message,
        )
        self.audio_streamer.attach(self.page)
        await self.audio_streamer.start()

    def _on_audio_message(self, payload: dict):
        if self.page:
            self.page.run_task(self._handle_audio_payload, payload)

    async def _handle_audio_payload(self, payload: dict):
        # logger.debug(Utils.pretty_print(payload))
        kind = payload.get("type")
        text = (payload.get("text") or "").strip()
        if not text:
            return
        self.input_box.value = text
        self.input_box.update()
        if kind == "final":
            self.send_message()

    async def _stop_mic(self):
        if self.audio_streamer:
            await self.audio_streamer.stop()
            self.audio_streamer = None

    def _append_history(self, role: str, content: str, image_filepath: str = None):
        try:
            bubble = ChatBubble(role, content, image_filepath)
            if role in ("assistant", "error"):
                self.replay_content = content

            style = {
                "user": STYLES["chat_user"],
                "assistant": STYLES["chat_assistant"],
                "error": STYLES["chat_error"],
            }.get(role, STYLES["chat_assistant"])

            bubble_slot = ft.Container(content=bubble, expand=85, **style)
            spacer = ft.Container(expand=15)
            row = ft.Row(
                controls=[spacer, bubble_slot] if role == "user" else [bubble_slot, spacer],
            )
            self.history.controls.insert(len(self.history.controls) - 2, row)
            self.history.update()
        except Exception as e:
            logger.error(f"failed to append to history: {repr(e)}")            

    def replay(self):
        Text_To_Speech.speak(text=self._cleanup_for_speech(self.replay_content), model=self.piper_model)

    def _remove_excess_linebreaks(self, text: str) -> str:
        code_block_pattern = r"```.*?```"
        parts = re.split(f"({code_block_pattern})", text, flags=re.DOTALL)

        def clean_text(t: str) -> str:
            return re.sub(r"\n{3,}", "\n\n", t)

        return "".join(
            part if re.match(code_block_pattern, part, flags=re.DOTALL) else clean_text(part)
            for part in parts
        )

    def _cleanup_content(self, content):
        return self._remove_excess_linebreaks(content)

    def _cleanup_for_speech(self, content):
        content = content.replace("*", "")
        content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
        content = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", content)
        content = re.sub(r"https?://\S+|www\.\S+", "", content).strip()
        content = re.sub(r"\[IMAGE:[^\]]*\]", "", content).strip()
        return content

    def _get_image(self, image_filename) -> str:
        image_path = Paths.get_image_path() / image_filename
        if not image_path.exists():
            Hub.download_file(f"images/{image_filename}", Paths.get_image_path())
        return str(image_path)

    def _flush_delta(self):
        if not self.delta_buffer:
            return
        self.stream_bubble.visible = True
        self.stream_bubble.append_content(self.delta_buffer)
        self.delta_buffer = ""
        self.stream_bubble.update()
        self.history.update()

    async def _schedule_flush(self, gen: int):
        await asyncio.sleep(0.1)
        if gen != self._stream_gen:
            return
        self._flush_delta()

    def on_incomming_message(self, message: dict):
        #logger.debug(f"incomming message:\n{Utils.pretty_print(message)}")

        try:
            if "status" in message:
                self.status_widget.on_status_message(message["status"])

            if "delta" in message and message["conversation_id"] == self.conversation_id:
                self.delta_buffer += message["delta"]
                if self.page:
                    self.page.run_task(self._schedule_flush, self._stream_gen)

            if "chat" in message:
                chat = message["chat"]
                if chat["conversation_id"] == self.conversation_id:
                    self._stream_gen += 1
                    self.delta_buffer = ""
                    self.stream_bubble.clear_content()
                    self.stream_bubble.visible = False
                    self.stream_bubble.update()
                    content = self._cleanup_content(chat["content"])
                    role = chat["role"]
                    if "take_photo" in message:
                        image_path = Paths.get_image_path() / message["take_photo"]["filename"]
                        self._append_history(role, content, str(image_path))
                    elif "generate_image" in message:
                        image_path = Paths.get_image_path() / message["generate_image"]["filename"]
                        self._append_history(role, content, str(image_path))
                    else:
                        self._append_history(role, content)
                    Text_To_Speech.speak(text=self._cleanup_for_speech(content), model=self.piper_model)
        except Exception as e:
            logger.error(f"failed to handle incomming message: {e}")

    def send_message(self):
        self.status_widget.clear_status()
        self.stream_bubble.clear_content()
        self.stream_bubble.visible = False
        self.stream_bubble.update()
        self.delta_buffer = ""

        message = (self.input_box.value or "").strip()
        if not message:
            return
        self.input_box.value = ""
        self.input_box.update()
        self._append_history("user", message)
        Hub.chat(self.contact_id, self.conversation_id, "user", message, self.temperature)