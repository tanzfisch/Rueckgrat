from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton)
from PySide6.QtCore import Qt, Signal, QEventLoop
from PySide6.QtWidgets import QApplication

class MessageBox(QWidget):
    result = Signal(bool)

    def __init__(self, message="Are you sure?", parent=None):
        super().__init__(parent)

        # Make overlay fill parent
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Layout for centering
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)

        # Card widget
        self.card = QWidget()
        self.card.setObjectName("overlay_dialog")
        self.card.setFixedWidth(parent.rect().width() * 0.8)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 20, 20, 20)

        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("Ok")
        cancel_btn = QPushButton("Cancel")

        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)

        card_layout.addWidget(label)
        card_layout.addSpacing(15)
        card_layout.addLayout(btn_layout)

        main_layout.addWidget(self.card)

        ok_btn.clicked.connect(self._ok)
        cancel_btn.clicked.connect(self._cancel)

    def _ok(self):
        self.result.emit(True)
        self.close()

    def _cancel(self):
        self.result.emit(False)
        self.close()

    def exec(self):
        """Optional modal-like behavior"""
        loop = QEventLoop()
        self.result.connect(loop.quit)
        self.show()
        loop.exec()

    @classmethod
    def open(cls, message="Are you sure?"):
        parent = QApplication.activeWindow()
        if parent is None:
            raise RuntimeError("No active window found")

        overlay = cls(message, parent)

        loop = QEventLoop()
        result_container = {}

        def store(value):
            result_container["value"] = value
            loop.quit()

        overlay.result.connect(store)

        overlay.show()
        loop.exec()

        return result_container.get("value", False)