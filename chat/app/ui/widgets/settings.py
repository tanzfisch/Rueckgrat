from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QEventLoop
from PySide6.QtWidgets import QApplication
from app.utils import RueckgratConfig


class SettingsDialog(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.config = RueckgratConfig()

        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WA_StyledBackground, True)

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)

        self.card = QWidget()
        self.card.setObjectName("overlay_dialog")
        self.card.setFixedWidth(parent.rect().width() * 0.8)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 20, 20, 20)

        # --- Fields ---
        self.host_input = QLineEdit(self.config.host)
        self.port_input = QLineEdit(self.config.port)
        self.cert_input = QLineEdit(self.config.server_cert)

        browse_btn = QPushButton("Browse")

        browse_btn.clicked.connect(self._browse_cert)

        def row(label_text, widget, extra=None):
            layout = QHBoxLayout()
            layout.addWidget(QLabel(label_text))
            layout.addWidget(widget)
            if extra:
                layout.addWidget(extra)
            return layout

        card_layout.addLayout(row("Host:", self.host_input))
        card_layout.addLayout(row("Port:", self.port_input))
        card_layout.addLayout(row("Certificate:", self.cert_input, browse_btn))

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")

        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)

        card_layout.addSpacing(15)
        card_layout.addLayout(btn_layout)

        main_layout.addWidget(self.card)

        ok_btn.clicked.connect(self._ok)
        cancel_btn.clicked.connect(self._cancel)

    def _browse_cert(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Certificate")
        if path:
            self.cert_input.setText(path)

    def _ok(self):
        self.config.host = self.host_input.text()
        self.config.port = self.port_input.text()
        self.config.server_cert = self.cert_input.text()
        self.close()

    def _cancel(self):
        self.close()

    @classmethod
    def open(cls):
        parent = QApplication.activeWindow()
        if parent is None:
            raise RuntimeError("No active window found")

        dialog = cls(parent)
        dialog.show()