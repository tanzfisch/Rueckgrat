from PySide6.QtWidgets import QWidget, QTextEdit, QVBoxLayout, QSizePolicy, QStyleOption, QStyle, QLabel
from PySide6.QtGui import QPainter
from PySide6.QtCore import Qt, Signal

class ChatBubbleTextEdit(QTextEdit):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setObjectName("chatBubble")
        self.setProperty("role", text)
        self.setReadOnly(True)        
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def wheelEvent(self, event):
        event.ignore()

class ChatBubble(QWidget):
    def __init__(self, role, content):
        super().__init__()

        self.setObjectName("chatBubble")
        self.setProperty("role", role)
        self.setAutoFillBackground(True)

        layout = QVBoxLayout(self)

        self.text = ChatBubbleTextEdit(content)
        self.text.document().contentsChanged.connect(self.adjust_height)
        layout.addWidget(self.text)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def adjust_height(self):
        doc = self.text.document()
        self.text.setFixedHeight(int(doc.size().height()))

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_height()

class OneLineBubble(QWidget):
    clicked = Signal(str, int)

    def __init__(self, username: str ="", id: int="-1"):
        super().__init__()

        self.id = int(id)

        # TODO move this to style.qss
        self.setStyleSheet("""
            QWidget {
                border-radius: 16px;
                padding: 10px;
                background-color: #3A3A3A;
                color: white;
            }
        """)

        layout = QVBoxLayout(self)
        self.label = QLabel(username)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def get_id(self):
        return self.id

    def set(self, text, id):
        self.label.setText(text)
        self.id = id

    def mousePressEvent(self, event):
        self.clicked.emit(str(self.label.text()), int(self.id)) 