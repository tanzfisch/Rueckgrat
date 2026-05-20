from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PySide6.QtCore import Qt, QEventLoop, QEvent
from PySide6.QtGui import QPixmap

from pathlib import Path

class ImageOverlay(QWidget):
    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)

        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WA_StyledBackground, True)

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)

        self.pixmap = QPixmap(image_path)
        if self.pixmap.isNull():
            raise RuntimeError(f"Could not load image: {image_path}")

        main_layout.addWidget(self.image_label)

        self.updatePixmap()

        parent.installEventFilter(self)        

    def eventFilter(self, watched, event):
        if watched == self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(self.parent().rect())
            self.updatePixmap()
        return super().eventFilter(watched, event)

    def updatePixmap(self):
        if not self.pixmap:
            return
        
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                self.width(),
                self.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)

    def mousePressEvent(self, event):
        self.close()
        super().mousePressEvent(event)

    def exec(self):
        loop = QEventLoop()
        self.destroyed.connect(loop.quit)
        self.show()
        loop.exec()

    @classmethod
    def open(cls, image_path):
        parent = QApplication.activeWindow()
        if parent is None:
            raise RuntimeError("No active window found")

        overlay = cls(image_path, parent)

        loop = QEventLoop()
        overlay.destroyed.connect(loop.quit)

        overlay.show()
        loop.exec()