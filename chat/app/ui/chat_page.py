import json
import re
from PySide6.QtWidgets import ( QWidget, QVBoxLayout, QTextEdit, QPushButton, QLabel, QHBoxLayout, QScrollArea, QMenu )
from PySide6.QtGui import QIcon, QFont
from PySide6.QtCore import Qt, QTimer, QSize, QPoint

from app.ui import BasePage
from app.ui.widgets import ChatBubble, ContactHeader, EmojiPicker
from app.speech import Speech
from app.utils import Backend, Contact
from pathlib import Path

from common import Logger
logger = Logger(__name__).get_logger()

class HistoryContainer(QWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refreshSize()

    def refreshSize(self):
        for wrapper in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            for bubble in wrapper.findChildren(ChatBubble, options=Qt.FindDirectChildrenOnly):
                bubble.setFixedWidth(int(self.width() * 0.85))

class ChatPage(BasePage):
    def __init__(self, navigator):
        super().__init__(navigator)

        chat_layout = QVBoxLayout(self)

        self.contact_header = ContactHeader()
        self.contact_header.go_back.connect(self.on_go_back)
        chat_layout.addWidget(self.contact_header)

        # history section
        self.history_scroll_area = QScrollArea()
        self.history_scroll_area.setWidgetResizable(True)

        self.history_container = HistoryContainer()
        self.history_layout = QVBoxLayout(self.history_container)
        self.history_layout.setSpacing(10)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_layout.addStretch()

        self.history_scroll_area.setWidget(self.history_container)

        # input section
        input_layout = QHBoxLayout()
        input_container = QWidget()
        input_container.setLayout(input_layout)
        input_container.setObjectName("input_container")

        self.menu_button = QPushButton()
        self.menu_button.setIcon(QIcon("app/icons/menu_light.png"))
        self.menu_button.setIconSize(QSize(24, 24))
        self.menu_button.clicked.connect(self.show_context_menu)
        input_layout.addWidget(self.menu_button, alignment=Qt.AlignmentFlag.AlignBottom)

        self.input_box = QTextEdit()
        self.input_box.setObjectName("input_box")
        self.input_box.setPlaceholderText("Type here... (Ctrl+Enter to send)")
        self.input_box.setAcceptRichText(False)        
        self.input_box.setFixedHeight(40)
        self.input_box.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input_box.textChanged.connect(self.adjust_input_box_height)
        self.input_box.installEventFilter(self)
        input_layout.addWidget(self.input_box, alignment=Qt.AlignmentFlag.AlignBottom)

        self.emoji_button = QPushButton()
        self.emoji_button.setIcon(QIcon("app/icons/emoji_light.png"))
        self.emoji_button.clicked.connect(self.openEmojiPicker)
        self.emoji_button.setIconSize(QSize(24, 24))
        input_layout.addWidget(self.emoji_button, alignment=Qt.AlignmentFlag.AlignBottom)

        self.mic_toggle_btn = QPushButton()
        self.mic_toggle_btn.setIcon(QIcon("app/icons/mic_off_light.png"))
        self.mic_toggle_btn.setCheckable(True)
        self.mic_toggle_btn.setChecked(False)
        self.mic_toggle_btn.setIconSize(QSize(24, 24))
        self.mic_toggle_btn.toggled.connect(self.on_mic_toggle)
        input_layout.addWidget(self.mic_toggle_btn, alignment=Qt.AlignmentFlag.AlignBottom)

        send_btn = QPushButton()
        send_btn.setIcon(QIcon("app/icons/send_light.png"))
        send_btn.clicked.connect(self.send_message)
        send_btn.setIconSize(QSize(24, 24))
        input_layout.addWidget(send_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        
        chat_layout.addWidget(self.history_scroll_area)
        chat_layout.addWidget(input_container)        

    def openEmojiPicker(self):
        button_pos = self.emoji_button.mapToGlobal(QPoint(0, 0))
        result = EmojiPicker.open(button_pos)
        self.input_box.setPlainText(self.input_box.toPlainText() + result)
        
    def on_go_back(self):
        self.navigator("conversations", contact_id=self.contact_id)

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)

            widget = item.widget()
            child_layout = item.layout()

            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

            elif child_layout is not None:
                self.clear_layout(child_layout)

    def clear_history(self):
        self.clear_layout(self.history_layout)
        self.history_layout.addStretch()

    def on_enter(self, **kwargs):
        self.contact_id = kwargs.get("contact_id")
        self.conversation_id = kwargs.get("conversation_id")

        self.contact = Contact(Backend.get_instance().get_contact(self.contact_id))
        self.contact_header.set_contact(self.contact)

        self.clear_history()

        messages = Backend.get_instance().get_messages(self.conversation_id)
        for message in messages:
            message_id = message["id"]
            attachements = Backend.get_instance().get_attachments(message_id)
            if attachements:
                image_path = self._get_image(attachements[0]["file_name"])
                self.append_history(message["role"], message["content"], image_path)
            else:
                self.append_history(message["role"], message["content"])

        self.input_box.setFocus()

        if self.contact.get_gender() == "male":
            default_piper = "en_US-hfc_male-medium"
            default_kokoro = "af_adam"
        else:
            default_piper = "en_US-libritts_r-medium"
            default_kokoro = "af_bella"

        self.kokoro_voice=default_kokoro # TODOself.contact.get("kokoro_voice_type") or default_kokoro
        self.piper_model=self.contact.get_voice_model() or default_piper

        self.temperature = float(self.contact.get_llm_temperature())

        Backend.get_instance().register_incomming_message(self.on_incomming_message)

    def on_leave(self):
        Backend.get_instance().unregister_incomming_message(self.on_incomming_message)

    def resizeEvent(self, event):
        self.adjust_input_box_height()
        super().resizeEvent(event)

    def adjust_input_box_height(self):
        doc_height = self.input_box.document().size().height()
        new_height = int(doc_height)

        min_height = 40
        max_height = self.window().height() * 0.3

        new_height = max(min_height, min(new_height, max_height))

        self.input_box.setFixedHeight(new_height)

        # Enable scroll only if max height reached
        if new_height >= max_height:
            self.input_box.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
        else:
            self.input_box.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            ) 

    def show_context_menu(self):
        menu = QMenu(self)

        replay_action = menu.addAction("... replay")
        replay_action.triggered.connect(self.replay)

        menu.adjustSize()
        menu_height = menu.sizeHint().height()
        pos = self.menu_button.mapToGlobal(QPoint(0, -menu_height))
        menu.exec(pos)

    def eventFilter(self, obj, event):
        if obj == self.input_box and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    def on_mic_toggle(self, checked):
        if checked:
            self.mic_toggle_btn.setIcon(QIcon("app/icons/mic_on_light.png"))
            # turn mic on
        else:
            self.mic_toggle_btn.setIcon(QIcon("app/icons/mic_off_light.png"))
            # turn mic off

    def append_history(self, role: str, content: str, image_filepath: str = None):
        bubble = ChatBubble(role, content, image_filepath)

        wrapper = QWidget()
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)

        if role == "user":            
            wrapper_layout.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignRight)
        elif role == "assistant" or role == "error":
            self.replay_content = content
            wrapper_layout.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignLeft)

        self.history_layout.insertWidget(self.history_layout.count() - 1, wrapper)
        
        QTimer.singleShot(10, self.history_container.refreshSize)
        QTimer.singleShot(50, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        scrollbar = self.history_scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def replay(self):
        Speech.speak(self._cleanup_for_speech(self.replay_content), voice=self.kokoro_voice, model=self.piper_model, interface="piper")

    def _remove_excess_linebreaks(self, text: str) -> str:
        code_block_pattern = r"```.*?```"
        parts = re.split(f"({code_block_pattern})", text, flags=re.DOTALL)

        def clean_text(t: str) -> str:
            return re.sub(r"\n{2,}", "\n", t)

        return "".join(
            part if re.match(code_block_pattern, part, flags=re.DOTALL)
            else clean_text(part)
            for part in parts
        )

    def _cleanup_content(self, content):
        content = self._remove_excess_linebreaks(content)

        return content    
    
    def _cleanup_for_speech(self, content):
        content = content.replace("*", "")
        content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
        content = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", content)
        content = re.sub(r'https?://\S+|www\.\S+', '', content).strip()
        content = re.sub(r'\[IMAGE:[^\]]*\]', '', content).strip()    
        return content

    def _get_image(self, image_filename) -> str:
        image_path = Path("cache/images") / image_filename
        if not image_path.exists():
            Backend.get_instance().download(f"images/{image_filename}", "cache/images")

        return image_path

    def on_incomming_message(self, msg: dict):
        if "chat" in msg:
            chat = msg["chat"]
            content = self._cleanup_content(chat["content"])
            role = chat["role"]

            if "assistant_image" in msg:
                image = msg["assistant_image"]
                image_path = Path("cache/images") / image["filename"]
                self.append_history(role, content, image_path)
            elif "image" in msg:
                image = msg["image"]
                image_path = Path("cache/images") / image["filename"]
                self.append_history(role, content, image_path)
            else:
                self.append_history(role, content)

            try:
                Speech.speak(self._cleanup_for_speech(content), voice=self.kokoro_voice, model=self.piper_model, interface="piper")
            except Exception as e:
                logger.error(f"{e}")

    def send_message(self):
        message = self.input_box.toPlainText().strip()
        if not message:
            return
        self.input_box.clear()

        self.append_history("user", message)        
        Backend.get_instance().async_chat(self.contact_id, self.conversation_id, "user", message, self.temperature)