import asyncio
import random
import re
import flet as ft
from app.ui import theme

from app.ui import BasePage
from app.ui.widgets import ChatBubble, Header, EmojiPicker, StatusWidget, PollView, MapView, PriceView, FileCards, FilesDock, MessageBox, show_protocol
from app.audio import Text_To_Speech
from app.utils import Hub, Contact, Paths, AudioStreamer, RueckgratConfig, Capabilities, ContactFiles, Backroom
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
        self._play_btn = None       # play button of the bubble being spoken, it shows stop meanwhile
        self.delta_buffer = ""
        self._stream_gen = 0
        self._stream_message_id = None
        self._finished_message_ids = set()
        self._spoken_id = None      # the streaming reply that is spoken while it is written
        self._spoken_text = ""      # its text so far
        self._bubbles: dict[int, ChatBubble] = {}       # message id -> its bubble in the history
        self._slots: dict[int, ft.Column] = {}          # message id -> the column of its bubble and button row, a poll, map or price ranking goes in between
        self._pending_images: dict[int, list[str]] = {}  # message id -> image file names that came before its bubble
        self._pending_files: dict[int, list] = {}       # message id -> text file cards that came before its bubble
        self._pending_data: dict[int, dict] = {}        # message id -> {kind: value} a tool pushed before its bubble (_set_data)
        self._protocol_buttons: set[int] = set()        # #215 the message ids of reports that have their 'open protocol' button
        self.user_role_name = ""   # set from the user's own character profile in on_enter
        self._told_typing = False   # #167 typing was already sent for this visit, so a held reach-out is dropped once

        self.files_btn = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            tooltip="files",
            width=40,
            height=40,
            style=theme.STYLES["icon_button"]["style"],
            on_click=lambda e: self.toggle_files(),
        )
        self.header = Header(navigator, actions=[self.files_btn])
        self.header.on_go_back = self.on_go_back

        self.history = ft.ListView(expand=True, spacing=4, padding=0, auto_scroll=True)
        self.status_widget = StatusWidget(on_cancel_job=self._confirm_cancel_job)
        self.status_row = ft.Row(controls=[self.status_widget])   # always the last row, messages go above it

        self._input_focused = False
        self._enter_sends = RueckgratConfig().enter_sends   # user setting, else ctrl+enter sends
        self.input_box = ft.TextField(
            hint_text="Type here...",
            multiline=True,
            min_lines=1,
            max_lines=8,
            shift_enter=self._enter_sends,   # enter sends, shift+enter is a new line
            on_submit=(lambda e: self.send_message()) if self._enter_sends else None,
            # autofocus, not focus(): flet 1.0.4 focus() only reaches the normal focus node, a shift_enter field has another one
            autofocus=True,
            expand=True,
            border=ft.NoInputBorder(),
            on_focus=lambda e: setattr(self, "_input_focused", True),
            on_blur=lambda e: setattr(self, "_input_focused", False),
            on_change=lambda e: self._on_typing(),
            text_style=ft.TextStyle(
                font_family="DejaVu Sans",
                font_family_fallback=["Noto Color Emoji"],
            ),            
        )

        self.icon_size = 24

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
        # speech and the mic only while the hub can do them (Capabilities, live)
        self.mute_slot = Capabilities.bind(ft.Container(content=ft.Stack(expand=True, controls=[self.mute_btn, self.tts_wave])), "tts")
        self.mic_slot = Capabilities.bind(ft.Container(
            padding=ft.Padding(left=8, top=0, right=8, bottom=0),
            content=ft.Stack(expand=True, controls=[self.mic_btn, self.wave]),
        ), "stt")

        self.bubble = ft.Container(
            border_radius=20,
            bgcolor=theme.INPUT_BAR,
            padding=ft.Padding(left=8, top=8, right=8, bottom=8),
            content=ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                controls=[
                    ft.Container(
                        expand=True,
                        padding=ft.Padding(left=8, top=0, right=0, bottom=0),
                        content=ft.Column(
                            expand=True,
                            controls=[
                                self.input_box,                                
                                ft.Container(
                                    expand=True,                                    
                                    content=ft.Row(
                                        expand=True,
                                        controls=[
                                            ft.Container(expand=True),  # spacer
                                            self.emoji_btn,
                                            self.mute_slot,
                                            self.mic_slot,
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

        self.conversation = ft.Container(
            padding=20,
            content=ft.Column(
                expand=True,
                controls=[
                    self.header,
                    self.history,
                    self.bubble,
                ],
            ),
        )
        self.files_dock = FilesDock(self.conversation)     # the contact's files, docked right or over the conversation
        self.controls = [self.files_dock]

    def did_mount(self):
        self.page.on_keyboard_event = self._on_keyboard
        self.files_dock.attach()

    def toggle_files(self):
        """the contact's files: the same for all its conversations, reached through this one"""
        self.files_dock.toggle(ContactFiles(self.contact_id, self.conversation_id, self.contact.get_name() if self.contact else ""))

    def _on_keyboard(self, e: ft.KeyboardEvent):
        if e.key == "Enter" and e.ctrl and self._input_focused and not self._enter_sends:   # enter_sends: on_submit sends
            self.send_message()

    async def open_emoji_picker(self, e=None):
        result = await EmojiPicker.open(self.page)
        if result:
            self.input_box.value = (self.input_box.value or "") + result
            self.input_box.update()

    def on_go_back(self, e=None):
        self.navigator.back()

    def on_system_back(self) -> bool:
        """android back with the keyboard open only hides it, the next back leaves. True if it did"""
        # the focus, not page.media: flet measures view_insets inside the Scaffold body, there the keyboard is always 0
        logger.info(f"TEMP system back: input focused {self._input_focused}, insets {self.page.media.view_insets.bottom}")
        if not self._input_focused:
            return False
        self._input_focused = False   # on_blur follows, the next back leaves even if it is late
        self.page.run_task(self._hide_keyboard)
        return True

    async def _hide_keyboard(self):
        # flet 1.0.4 has no blur(): a field that can't take focus gives it up and the keyboard closes
        self.input_box.can_request_focus = False
        self.input_box.update()
        await asyncio.sleep(0.3)
        self.input_box.can_request_focus = True   # a tap opens it again
        self.input_box.update()

    def clear_history(self):
        self.status_widget.clear_status()
        self._stream_message_id = None
        self._finished_message_ids.clear()
        self._bubbles.clear()
        self._slots.clear()
        self._pending_images.clear()
        self._pending_files.clear()
        self._pending_data.clear()
        self._protocol_buttons.clear()
        self._play_btn = None
        self.history.controls = [self.status_row]
        self.history.update()

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        self.conversation_id = kwargs.get("conversation_id")
        self.contact = Contact(Hub.get_contact(self.contact_id))
        self.header.set_contact(self.contact)
        self.files_dock.attach()    # again after a leave (did_mount only comes once)
        user_data = Hub.get_user_data() or {}
        profile = user_data.get("profile") or {}
        self.user_role_name = (profile.get("name") or "").strip() or Hub.user_name
        self.clear_history()

        for message in Hub.get_messages(self.conversation_id):
            image_paths = [self._get_image(item["file_name"]) for item in message.get("attachments", [])
                           if str(item.get("file_type") or "").startswith("image/") and item.get("file_name")]
            self._append_history(message["role"], message["content"], image_paths, message_id=message["id"],
                                 sources=message.get("sources"), data=message.get("data"), text_files=message.get("text_files"))
        # a reply still being made is already loaded with its text so far: skip its deltas, the final "chat" fills it
        self._finished_message_ids.update(self._bubbles)

        self.temperature = float(self.contact.get_llm_temperature())
        Hub.register_incomming_message(self.on_incomming_message)
        Capabilities.listen(self._on_capabilities)
        self.status_widget.on_jobs(Backroom.jobs())     # #215 the running agent jobs' rows
        Backroom.add_listener(self._on_jobs)
        self._told_typing = False
        Hub.register_connection_state(self._on_connection_state)
        Hub.contact_opened(self.contact_id, self.conversation_id)

    def on_leave(self):
        if self.page:
            self.page.run_task(self._stop_mic)
            self.files_dock.detach()
        if self.contact_id is not None:
            Hub.contact_closed(self.contact_id)
        Hub.unregister_connection_state(self._on_connection_state)
        Hub.unregister_incomming_message(self.on_incomming_message)
        Capabilities.unlisten(self._on_capabilities)
        Backroom.remove_listener(self._on_jobs)

    def _on_connection_state(self, state: str):
        """#167 after a reconnect the hub no longer knows this contact is open"""
        if state == "reconnected" and self.contact_id is not None and self.conversation_id is not None:
            Hub.contact_opened(self.contact_id, self.conversation_id)

    def _on_typing(self):
        """#167 the first keystroke of this visit drops a still-held reach-out"""
        if (self.input_box.value or "").strip():
            self._tell_typing()

    def _tell_typing(self):
        if self._told_typing or self.contact_id is None or self.conversation_id is None:
            return
        self._told_typing = True
        Hub.typing(self.contact_id, self.conversation_id)

    def _confirm_cancel_job(self, job_id: str) -> bool:
        """#152 the cancel button of a job's row: asks first. False: the row's button stays (the job_update removes the row)"""
        job = Backroom.job(job_id) or {}
        MessageBox.confirm(self.page, f"Cancel the job \"{job.get('name') or 'background job'}\"?", lambda: Hub.cancel_job(job_id),
                           title="Cancel job", ok_text="Cancel job")
        return False

    def _on_jobs(self, job_id):
        """#215 Backroom: a job got its report message (or a snapshot came): its 'open protocol' button under it"""
        jobs = [Backroom.job(job_id)] if job_id is not None else Backroom.jobs()
        added = False
        for job in jobs:
            if job and job.get("report_message_id") in self._bubbles and job["report_message_id"] not in self._protocol_buttons:
                added = self._add_protocol_button(job["report_message_id"], self._bubbles[job["report_message_id"]], job) or added
        if added:
            try:
                self.history.update()
            except RuntimeError:
                pass

    def _add_protocol_button(self, message_id: int, bubble: ChatBubble, job: dict) -> bool:
        if message_id in self._protocol_buttons:
            return False
        self._protocol_buttons.add(message_id)
        bubble.action_row.add_button(ft.IconButton(
            icon=ft.Icons.RECEIPT_LONG, icon_size=16, tooltip="open protocol",
            on_click=lambda e, job_id=job["job_id"]: show_protocol(self.page, Backroom.job(job_id) or job),
        ))
        return True

    def _on_capabilities(self, lost: set):
        """speech or the mic went away while in use: they stop (their buttons are hidden by Capabilities.bind)"""
        if "tts" in lost:
            if self.mute_btn.selected:
                self.on_mute_toggle()       # off, stops the speech
            elif Text_To_Speech.state != "idle":
                Text_To_Speech.kill_current_speech()
        if "stt" in lost and self.mic_btn.selected:
            self.on_mic_toggle()
            if self.page:
                MessageBox.error(self.page, "Speech recognition is not available right now, the mic is off.", title="Mic off")

    def on_mic_toggle(self, e=None):
        self.mic_btn.selected = not self.mic_btn.selected
        if self.mic_btn.selected:
            self.mic_btn.icon = ft.Icons.MIC
            self._tell_typing()
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
        try:
            self.audio_streamer.attach(self.page)
            await self.audio_streamer.start()
        except Exception as e:    # e.g. no audio device or sounddevice missing: the button goes back to off, like the translate page
            logger.error(f"failed to start the mic: {e!r}")
            await self._stop_mic()
            self.mic_btn.selected = False
            self.mic_btn.icon = ft.Icons.MIC_OFF
            self.mic_btn.update()
            return
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
        if kind == "mic.off":
            if self.mic_btn.selected:
                self.on_mic_toggle()
            return
        if kind == "error":     # the hub can't transcribe (speech recognition down): the mic goes off and says why
            if self.mic_btn.selected:
                self.on_mic_toggle()
                MessageBox.error(self.page, f"{(payload.get('text') or 'speech recognition failed').capitalize()}, the mic is off.", title="Mic off")
            return
        text = (payload.get("text") or "").strip()
        if not text:
            return
        if Text_To_Speech.state != "idle":  # the user talks over the reply: stop speaking it
            Text_To_Speech.kill_current_speech()
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

    def _append_history(self, role: str, content: str, image_filepaths: list[str] | None = None, message_id: int = None, 
                        sources: list | None = None, data: dict | None = None, text_files: list | None = None) -> ChatBubble | None:
        try:
            bubble = ChatBubble(role, content, image_filepaths)
            if message_id is not None:
                self._bubbles[message_id] = bubble
            if role == "assistant":
                bubble.action_row.add_button(Capabilities.bind(ft.IconButton(
                    icon=ft.Icons.PLAY_ARROW, icon_size=16, tooltip="Play",
                    on_click=lambda e, b=bubble: self._on_play(e.control, b),
                ), "tts"))
            if sources:
                bubble.action_row.set_sources(sources)
            report_of = Backroom.for_report(message_id) if role == "assistant" else None
            if report_of:   # #215 the report of a job or pass
                self._add_protocol_button(message_id, bubble, report_of)

            style = {
                "user": theme.STYLES["chat_user"],
                "assistant": theme.STYLES["chat_assistant"],
                "error": theme.STYLES["chat_error"],
            }.get(role, theme.STYLES["chat_assistant"])

            # the bubble with its button row under it
            bubble_slot = ft.Column(
                controls=[ft.Container(content=bubble, **style), bubble.action_row],
                expand=85, spacing=0, tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
            spacer = ft.Container(expand=15)
            row = ft.Row(
                controls=[spacer, bubble_slot] if role == "user" else [bubble_slot, spacer],
                data=bubble,
            )
            self.history.controls.insert(self.history.controls.index(self.status_row), row)
            if message_id is not None:
                self._slots[message_id] = bubble_slot
                self._set_data(message_id, data)
                for spec in text_files or []:
                    self._set_files(message_id, spec)
            self.history.update()
            return bubble
        except Exception as e:
            logger.error(f"failed to append to history: {repr(e)}")
            return None            

    def _data_view(self, message_id: int, kind: str, value: dict) -> ft.Control | None:
        """the view of one kind of a message's data, None for a kind this client does not show"""
        if kind == "poll":
            return PollView(value, on_submit=lambda chosen: self._submit_poll(message_id, chosen))
        if kind == "map":
            return MapView(value)
        if kind == "prices":
            return PriceView(value)
        return None

    def _set_data(self, message_id: int, data: dict | None):
        """shows a message's data ({kind: value}) under its bubble, a view per kind: the poll right under the bubble, the others
        above the button row. a kind pushed again replaces its view in place, a kind this client does not know is left out"""
        slot = self._slots.get(message_id)
        if slot is None or not isinstance(data, dict):
            return
        for kind, value in data.items():
            try:
                view = self._data_view(message_id, kind, value) if isinstance(value, dict) else None
                if view is None:
                    continue
                container = ft.Container(content=view, data=kind, margin=ft.Margin(left=0, top=8, right=0, bottom=0), **theme.STYLES["chat_assistant"])
                index = next((i for i, c in enumerate(slot.controls) if getattr(c, "data", None) == kind), None)
                if index is not None:
                    slot.controls[index] = container
                else:
                    slot.controls.insert(1 if kind == "poll" else len(slot.controls) - 1, container)
            except Exception as e:
                logger.error(f"failed to show {kind} data: {repr(e)}")

    def _set_files(self, message_id: int, spec: dict):
        try:
            slot = self._slots.get(message_id)
            if slot is None:
                return
            cards = next((c.content for c in slot.controls if isinstance(c, ft.Container) and isinstance(c.content, FileCards)), None)
            if cards is None:
                cards = FileCards(message_id)
                slot.controls.insert(len(slot.controls) - 1, ft.Container(content=cards, margin=ft.Margin(left=0, top=8, right=0, bottom=0)))
            cards.add(spec)
        except Exception as e:
            logger.error(f"failed to set files: {repr(e)}")

    def _submit_poll(self, message_id: int, chosen: list[str]) -> bool:
        """the poll's choice goes to the hub as the user's next message, the hub locks the poll with it"""
        self.status_widget.clear_status()
        return self._send(f"Chosen: {', '.join(chosen)}", poll_answer={"message_id": message_id, "chosen": chosen})

    def _on_play(self, button: ft.IconButton, bubble: ChatBubble):
        """play button under an answer: speaks it with the contact's voice, a tap while it plays stops it"""
        if button is self._play_btn and Text_To_Speech.state != "idle":
            Text_To_Speech.kill_current_speech()   # _tts_loop ends and shows play again
            return
        self._speak(bubble.raw_content, play_btn=button)

    def _show_playing(self, button: ft.IconButton | None):
        """the play button of the bubble being spoken shows stop, the one before goes back to play"""
        if button is self._play_btn:
            return
        for btn, icon in ((self._play_btn, ft.Icons.PLAY_ARROW), (button, ft.Icons.STOP)):
            if btn:
                btn.icon = icon
                try:
                    btn.update()
                except RuntimeError:
                    pass    # its bubble is not on the page (anymore)
        self._play_btn = button

    def _speak(self, content: str, message_id: int | None = None, play_btn: ft.IconButton | None = None, streaming: bool = False):
        """speaks a message and animates the bars on the mute button while it is generated and played.
        streaming: the reply is still being written, Text_To_Speech.stream_text hands over the rest"""
        self._show_playing(play_btn)
        speak = Text_To_Speech.speak_stream if streaming else Text_To_Speech.speak
        speak(text=content, voice=self.contact.get_voice_id(), message_id=message_id)
        if not self._tts_running and self.page:
            self._tts_running = True
            self.page.run_task(self._tts_loop)

    @staticmethod
    def _make_wave():
        """the scrolling bars overlay, put into a Stack on top of a button"""
        bars = [
            ft.Container(
                width=4, height=0, border_radius=2, bgcolor=theme.TEXT,
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
            logger.debug(f"tts bars stopped: {repr(e)}")
        finally:
            self._tts_running = False
            try:
                for bar in self.tts_wave_bars:
                    bar.height = 0
                self.tts_wave.visible = False
                self.tts_wave.update()
                if Text_To_Speech.state == "idle":
                    self._show_playing(None)
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

    def _get_image(self, image_filename) -> str:
        image_path = Paths.get_image_path() / image_filename
        if not image_path.exists():
            Hub.download_file(f"images/{image_filename}", Paths.get_image_path())
        return str(image_path)

    def _flush_delta(self):
        if not self.delta_buffer:
            return
        bubble = self._bubbles.get(self._stream_message_id) or self._append_history("assistant", "", message_id=self._stream_message_id)
        bubble.append_content(self.delta_buffer)
        self.delta_buffer = ""
        bubble.update()
        self.history.update()

    async def _schedule_flush(self, gen: int):
        await asyncio.sleep(0.1)
        if gen != self._stream_gen:
            return
        self._flush_delta()

    def _drop_stream(self, message_id: int | None = None):
        """removes the reply that is streaming, its late deltas are ignored"""
        for finished in (message_id, self._stream_message_id):
            if finished is not None:
                self._finished_message_ids.add(finished)
                self._remove_bubble(finished)
        self._stream_message_id = None
        self._stream_gen += 1
        self.delta_buffer = ""
        self._spoken_id = None

    def _speak_delta(self, message_id: int | None, delta: str):
        """with speech on, a reply is spoken while it streams: its first delta starts it, the others add to it"""
        if message_id is None:
            return
        if message_id != self._spoken_id:
            if not self.mute_btn.selected:
                return
            self._spoken_id, self._spoken_text = message_id, delta
            self._speak(delta, message_id, streaming=True)
            return
        self._spoken_text += delta
        Text_To_Speech.stream_text(message_id, self._spoken_text)

    def _remove_bubble(self, message_id: int):
        bubble = self._bubbles.pop(message_id, None)
        self._slots.pop(message_id, None)
        if bubble:
            self.history.controls = [row for row in self.history.controls if row.data is not bubble]
            self.history.update()

    def _merge_user_message(self, content: str):
        """the hub merged the follow-up into the previous user message: drop the follow-up's bubble, update the previous one"""
        rows = [row for row in self.history.controls if isinstance(row.data, ChatBubble) and row.data.role == "user"]
        if len(rows) < 2:
            return
        self.history.controls.remove(rows[-1])
        previous = rows[-2].data
        previous.clear_content()
        previous.append_content(content)
        self.history.update()

    def _replace_user_message(self, content: str):
        """the hub fenced code in the user message: the last user bubble shows the stored text"""
        rows = [row for row in self.history.controls if isinstance(row.data, ChatBubble) and row.data.role == "user"]
        if not rows:
            return
        rows[-1].data.clear_content()
        rows[-1].data.append_content(content)
        self.history.update()

    def on_incomming_message(self, message: dict):
        if not "delta" in message:
            logger.debug(f"incomming message:\n{Utils.pretty_print(message)}")

        try:
            if "status" in message and message["status"].get("conversation_id", self.conversation_id) == self.conversation_id:
                self.status_widget.on_status_message(message["status"])

            if "job_update" in message:     # #152 #215 background jobs, shown whatever conversation is open
                self.status_widget.on_job_update(message["job_update"])
            if "jobs" in message:           # the hub's snapshot (connect, get_jobs)
                self.status_widget.on_jobs((message["jobs"] or {}).get("items") or [])

            if "delta" in message and message["conversation_id"] == self.conversation_id:
                message_id = message.get("message_id")
                if message_id is not None and message_id in self._finished_message_ids:
                    return
                self._stream_message_id = message_id
                self.delta_buffer += message["delta"]
                self._speak_delta(message_id, message["delta"])
                if self.page:
                    self.page.run_task(self._schedule_flush, self._stream_gen)

            if "attachment" in message:
                self._on_attachment(message["attachment"])

            if "text_files" in message and message["text_files"].get("conversation_id") == self.conversation_id:
                spec = message["text_files"]
                message_id = spec.get("message_id")
                if self._slots.get(message_id):
                    self._set_files(message_id, spec)
                    self.history.update()
                else:
                    self._pending_files.setdefault(message_id, []).append(spec)

            if "data" in message and message["data"].get("conversation_id") == self.conversation_id:
                pushed = message["data"]
                message_id = pushed.get("message_id")
                if self._slots.get(message_id):
                    self._set_data(message_id, {pushed.get("kind"): pushed.get("value")})
                    self.history.update()
                else:
                    self._pending_data.setdefault(message_id, {})[pushed.get("kind")] = pushed.get("value")

            if "cancelled" in message and message["cancelled"]["conversation_id"] == self.conversation_id:
                self._drop_stream(message["cancelled"].get("message_id"))

            if "fenced" in message and message["fenced"]["conversation_id"] == self.conversation_id:
                self._replace_user_message(message["fenced"]["content"])

            if "merged" in message and message["merged"]["conversation_id"] == self.conversation_id:
                self._merge_user_message(message["merged"]["content"])

            if "chat" in message:
                chat = message["chat"]
                if chat["conversation_id"] == self.conversation_id:
                    self.files_dock.refresh()     # the reply may have written files (bash, run_code). only when it is open
                    message_id = chat.get("message_id", self._stream_message_id)   # read before the stream id is reset
                    if self._stream_message_id is not None:
                        self._finished_message_ids.add(self._stream_message_id)
                        self._stream_message_id = None
                    self._stream_gen += 1
                    self.delta_buffer = ""
                    content = self._cleanup_content(chat["content"])
                    role = chat["role"]
                    image_filenames = self._pending_images.pop(message_id, [])
                    if not image_filenames:
                        if "take_photo" in message:
                            image_filenames = [message["take_photo"]["filename"]]
                        elif "generate_image" in message:
                            image_filenames = [message["generate_image"]["filename"]]
                    image_paths = [self._get_image(name) for name in image_filenames]
                    sources = chat.get("sources") or []
                    data = self._pending_data.pop(message_id, {})
                    bubble = self._bubbles.get(message_id)
                    if bubble:
                        bubble.clear_content()
                        bubble.append_content(content)
                        bubble.update()
                        for image_path in image_paths:
                            bubble.add_image(image_path)
                        if sources:
                            bubble.action_row.set_sources(sources)
                            self.history.update()
                        if data:
                            self._set_data(message_id, data)
                            self.history.update()
                        files = self._pending_files.pop(message_id, None)
                        if files:
                            for spec in files:
                                self._set_files(message_id, spec)
                            self.history.update()
                    else:
                        self._append_history(role, content, image_paths, message_id=message_id, sources=sources, data=data,
                                             text_files=self._pending_files.pop(message_id, None))

                    if message_id is not None and message_id == self._spoken_id:
                        Text_To_Speech.stream_text(message_id, chat["content"], final=True)
                        self._spoken_id = None
                    elif self.mute_btn.selected:
                        self._speak(content, message_id)
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
        if bubble and message_id != self._stream_message_id:   # while it streams, the "chat" message adds the image once
            bubble.add_image(self._get_image(filename))
        else:
            pending = self._pending_images.setdefault(message_id, [])
            if filename not in pending:
                pending.append(filename)

    def send_message(self):
        self.status_widget.clear_status()

        message = (self.input_box.value or "").strip()
        if not message:
            return
        if not self._send(message):
            return
        self.input_box.value = ""
        self.input_box.update()

    def _send(self, content: str, poll_answer: dict | None = None) -> bool:
        """sends a user message and shows its bubble, False if it could not be sent"""
        if not Hub.chat(self.contact_id, self.conversation_id, "user", self.user_role_name, content, self.temperature, poll_answer):
            return False
        self._drop_stream()
        self._append_history("user", content)
        return True