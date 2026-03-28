from PySide6.QtWidgets import QWidget, QLabel, QGridLayout, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, Signal, QEventLoop
from PySide6.QtGui import QFont

class EmojiPicker(QWidget):
    result = Signal(str)

    def __init__(self, button_pos, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint)      
        self.emojis = [
            '😊', '😃', '😄', '😎', '😍', '😘', '🥰', '😇', 
            '🤣', '😜', '🤩', '🥳',
            '😌', '😴',
            '😶', '😳', '😲', '🤮',
            '😢', '😭', '😡', '😈', '😱', '😵',
            '🍆', '🍑', '💦', '😏', '🔥', '👅'
        ]

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        wrapper = QWidget()
        wrapper.setObjectName("overlay_dialog")
        layout.addWidget(wrapper)

        grid = QGridLayout(wrapper)
        grid.setSpacing(5)
        grid.setContentsMargins(5, 5, 5, 5)

        for index, emoji in enumerate(self.emojis):
            label = QLabel(emoji)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(QFont('Arial', 24))
            label.mousePressEvent = lambda event, e=emoji: self.emojiClicked(e)
            grid.addWidget(label, index // 6, index % 6)

        self.adjustSize()
        self.move(button_pos.x() - self.width() + 80, button_pos.y() - self.height())

    def emojiClicked(self, emoji):
        self.result.emit(emoji)
        self.close()

    def exec(self):
        loop = QEventLoop()
        self.result.connect(loop.quit)
        self.show()
        loop.exec()

    @classmethod
    def open(cls, button_pos):
        parent = QApplication.activeWindow()
        if parent is None:
            raise RuntimeError("No active window found")

        overlay = cls(button_pos, parent)

        loop = QEventLoop()
        result_container = {}

        def store(value):
            result_container["value"] = value
            loop.quit()

        overlay.result.connect(store)

        overlay.show()
        loop.exec()

        return result_container.get("value", "")