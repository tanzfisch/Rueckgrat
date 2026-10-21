import asyncio
import random
import re
import flet as ft
from app.ui.theme import STYLES, TEXT
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
        self.play_wave_animation = False
        self._wave_task = None
        self._tts_running = False   # tts bars on the mute button are animating
        self.delta_buffer = ""
        self._stream_gen = 0
        self._stream_message_id = None
        self._finished_message_ids = set()
        self._bubbles: dict[int, ChatBubble] = {}       # message id -> its bubble in the history
        self._pending_images: dict[int, str] = {}       # message id -> image file name that came before its bubble
        self.replay_content = ""
        self.user_role_name = ""   # set from the user's own character profile in on_enter

        self.contact_header = ContactHeader(navigator)
        self.contact_header.on_go_back = self.on_go_back

        self.history = ft.ListView(expand=True, spacing=10, padding=0, auto_scroll=True)
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
            border=ft.InputBorder.NONE,
            on_focus=lambda e: setattr(self, "_input_focused", True),
            on_blur=lambda e: setattr(self, "_input_focused", False),
            text_style=ft.TextStyle(
                font_family="DejaVu Sans",
                font_family_fallback=["Noto Color Emoji"],
            ),            
        )

        self.icon_size = 24

        self.menu_btn = ft.PopupMenuButton(
            icon=ft.Icons.MENU,
            icon_size=self.icon_size,
            items=[ft.PopupMenuItem(content="... replay", on_click=lambda e: self.replay())],
        )

        self.emoji_btn = ft.IconButton(
            icon=ft.Icons.EMOJI_EMOTIONS, 
            icon_size=self.icon_size,
            on_click=self.open_emoji_picker
        )

        self.mic_btn = ft.IconButton(
            icon=ft.Icons.MIC_OFF,
            icon_size=self.icon_size,
            selected=False,
            on_click=self.on_mic_toggle,
        )

        self.mute_btn = ft.IconButton(
            icon=ft.Icons.VOLUME_OFF,
            icon_size=self.icon_size,
            selected=False,
            on_click=self.on_mute_toggle,
        )        

        self.send_btn = ft.IconButton(
            icon=ft.Icons.SEND, 
            icon_size=self.icon_size,
            on_click=lambda e: self.send_message()
        )

        self.wave_bars, self.wave = self._make_wave()            # over the mic button
        self.tts_wave_bars, self.tts_wave = self._make_wave()    # over the mute button

        self.bubble = ft.Container(
            border_radius=20,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            padding=ft.Padding(left=8, top=8, right=8, bottom=8),
            content=ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                controls=[
                    ft.Container(
                        expand=True,
                        content=ft.Column(
                            expand=True,
                            controls=[
                                self.input_box,                                
                                ft.Container(
                                    expand=True,
                                    content=ft.Row(
                                        expand=True,
                                        controls=[
                                            self.menu_btn,
                                            ft.Container(expand=True),  # spacer
                                            self.emoji_btn,
                                            ft.Container(
                                                content=ft.Stack(
                                                    expand=True,
                                                    controls=[self.mute_btn, self.tts_wave],
                                                ),
                                            ),
                                            ft.Container(
                                                padding=ft.Padding(left=8, top=0, right=8, bottom=0),
                                                content=ft.Stack(
                                                    expand=True,
                                                    controls=[self.mic_btn, self.wave],
                                                ),
                                            ),                                            
                                            self.send_btn,
                                        ]
                                    )
                                )

                            ],                       
                        ),
                    ),
                ],
            ),
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
                        self.bubble,
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
        self._stream_message_id = None
        self._finished_message_ids.clear()
        self._bubbles.clear()
        self._pending_images.clear()
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
        user_data = Hub.get_user_data() or {}
        profile = user_data.get("profile") or {}
        self.user_role_name = (profile.get("name") or "").strip() or Hub.user_name
        self.clear_history()

        for message in Hub.get_messages(self.conversation_id):
            attachments = Hub.get_attachments(message["id"])
            if attachments:
                image_path = self._get_image(attachments[0]["file_name"])
                self._append_history(message["role"], message["content"], image_path, message_id=message["id"])
            else:
                self._append_history(message["role"], message["content"], message_id=message["id"])

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

    def on_mute_toggle(self, e=None):
        self.mute_btn.selected = not self.mute_btn.selected
        if self.mute_btn.selected:
            self.mute_btn.icon = ft.Icons.VOLUME_UP
        else:
            self.mute_btn.icon = ft.Icons.VOLUME_OFF
            Text_To_Speech.kill_current_speech()
        self.mute_btn.update()

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
        self._wave_task = asyncio.create_task(self._wave_loop())

    async def _wave_loop(self):
        try:
            while True:
                level = self.audio_streamer.level if self.audio_streamer else 0.0
                if not self.play_wave_animation:
                    self.play_wave_animation = level > 0.05

                if self.play_wave_animation:
                    self._scroll_wave(self.wave_bars, level)

                if self.wave.visible != self.play_wave_animation or self.play_wave_animation:
                    self.wave.visible = self.play_wave_animation
                    self.wave.update()

                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            pass

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
            self.play_wave_animation = False
            self.send_message()

    async def _stop_mic(self):
        self.play_wave_animation = False
        if self._wave_task:
            self._wave_task.cancel()
            self._wave_task = None
            self.wave.visible = False
            self.wave.update()
        if self.audio_streamer:
            await self.audio_streamer.stop()
            self.audio_streamer = None

    def _append_history(self, role: str, content: str, image_filepath: str = None, message_id: int = None) -> ChatBubble | None:
        try:
            bubble = ChatBubble(role, content, image_filepath)
            if message_id is not None:
                self._bubbles[message_id] = bubble
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
            return bubble
        except Exception as e:
            logger.error(f"failed to append to history: {repr(e)}")
            return None            

    def replay(self):
        if self.mute_btn.selected:
            self._speak(self.replay_content)

    def _speak(self, content: str):
        """speaks a message and animates the bars on the mute button while it is generated and played"""
        Text_To_Speech.speak(text=self._cleanup_for_speech(content), voice=self.contact.get_voice_id())
        if not self._tts_running and self.page:
            self._tts_running = True
            self.page.run_task(self._tts_loop)

    @staticmethod
    def _make_wave():
        """the scrolling bars overlay, put into a Stack on top of a button"""
        bars = [
            ft.Container(
                width=4, height=0, border_radius=2, bgcolor=TEXT,
                animate=ft.Animation(150, ft.AnimationCurve.EASE_IN_OUT),
            )
            for _ in range(5)
        ]
        wave = ft.Container(
            left=0, right=0, top=0, bottom=0,
            opacity=0.5, visible=False,
            ignore_interactions=True,  # it lies on top of the button, taps must go through to it
            content=ft.Row(
                controls=bars, spacing=4,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        return bars, wave

    @staticmethod
    def _scroll_wave(bars, level: float):
        """shift the bars left and add the newest level (0..1) on the right"""
        for left, right in zip(bars, bars[1:]):
            left.height = right.height
        bars[-1].height = level * 64

    async def _tts_loop(self):
        """follows Text_To_Speech.state: low pulse while the hub generates, speech-like bars while it plays"""
        tick = 0
        restart = True
        try:
            self.tts_wave.visible = True
            while Text_To_Speech.state != "idle":
                if Text_To_Speech.state == "playing":
                    level = random.uniform(0.1, 0.6)  # no playback level available, jitter in the range of normal speech
                else:
                    level = 0.1 if tick % 2 else 0.05  # generating: small pulse
                self._scroll_wave(self.tts_wave_bars, level)
                self.tts_wave.update()
                tick += 1
                await asyncio.sleep(0.15)
        except Exception as e:
            restart = False
            logger.debug(f"tts bars stopped: {repr(e)}")  # e.g. the page went away
        finally:
            self._tts_running = False
            try:
                for bar in self.tts_wave_bars:
                    bar.height = 0
                self.tts_wave.visible = False
                self.tts_wave.update()
            except Exception:
                pass
            if restart and Text_To_Speech.state != "idle" and self.page:
                self._tts_running = True  # a new speech started while we were stopping
                self.page.run_task(self._tts_loop)

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
        if not "delta" in message:
            logger.debug(f"incomming message:\n{Utils.pretty_print(message)}")

        try:
            if "status" in message:
                self.status_widget.on_status_message(message["status"])

            if "delta" in message and message["conversation_id"] == self.conversation_id:
                message_id = message.get("message_id")
                if message_id is not None and message_id in self._finished_message_ids:
                    return
                self._stream_message_id = message_id
                self.delta_buffer += message["delta"]
                if self.page:
                    self.page.run_task(self._schedule_flush, self._stream_gen)

            if "attachment" in message:
                self._on_attachment(message["attachment"])

            if "chat" in message:
                chat = message["chat"]
                if chat["conversation_id"] == self.conversation_id:
                    message_id = chat.get("message_id", self._stream_message_id)   # read before the stream id is reset
                    if self._stream_message_id is not None:
                        self._finished_message_ids.add(self._stream_message_id)
                        self._stream_message_id = None
                    self._stream_gen += 1
                    self.delta_buffer = ""
                    self.stream_bubble.clear_content()
                    self.stream_bubble.visible = False
                    self.stream_bubble.update()
                    content = self._cleanup_content(chat["content"])
                    role = chat["role"]
                    image_filename = self._pending_images.pop(message_id, None)
                    if image_filename is None:
                        if "take_photo" in message:
                            image_filename = message["take_photo"]["filename"]
                        elif "generate_image" in message:
                            image_filename = message["generate_image"]["filename"]
                    image_path = self._get_image(image_filename) if image_filename else None
                    self._append_history(role, content, image_path, message_id=message_id)

                    if self.mute_btn.selected:
                        self._speak(content)
        except Exception as e:
            logger.error(f"failed to handle incomming message: {e}")

    def _on_attachment(self, attachment: dict):
        """the hub attached an image to a message (the image may not exist yet): show the placeholder
        on its bubble and start the download. if the bubble is not there yet, the "chat" message picks it up"""
        if attachment.get("conversation_id") != self.conversation_id:
            return
        message_id = attachment.get("message_id")
        filename = attachment.get("filename")
        if message_id is None or not filename:
            return
        bubble = self._bubbles.get(message_id)
        if bubble:
            bubble.set_image(self._get_image(filename))
        else:
            self._pending_images[message_id] = filename

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
        Hub.chat(self.contact_id, self.conversation_id, "user", self.user_role_name, message, self.temperature)