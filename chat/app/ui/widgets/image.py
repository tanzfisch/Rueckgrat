from PySide6.QtWidgets import QLabel, QVBoxLayout, QStackedLayout, QWidget, QSizePolicy
from PySide6.QtCore import QTimer, QFile, Qt, QSize
from PySide6.QtGui import QPixmap, QMovie
from pathlib import Path

from .image_overlay import ImageOverlay

from common import Logger
logger = Logger(__name__).get_logger()

class Image(QWidget):
    def __init__(self, image_path: Path, size: QSize = None, parent=None):
        super().__init__(parent)
        self.size = size
        self.image_path = image_path
        self.pixmap = None
        self.init_ui()

    def init_ui(self):
        if self.size:
            self.setFixedSize(self.size)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)

        # loading page
        self.loading_label = QLabel()
        movie = QMovie("app/icons/loading.gif")
        movie.setSpeed(40)
        self.loading_label.setMovie(movie)
        movie.start()

        self.loading_page = QWidget()
        self.loading_page.setObjectName("transparent")
        loading_layout = QVBoxLayout(self.loading_page)
        loading_layout.setContentsMargins(0, 0, 0, 0)
        loading_layout.addWidget(self.loading_label, alignment=Qt.AlignCenter)
        self.stack.addWidget(self.loading_page)

        # image page
        self.image_label = QLabel()
        if not self.size:
            self.image_label.setScaledContents(True)
        else:
            self.image_label.setFixedSize(self.size)            

        self.image_page = QWidget()        
        image_layout = QVBoxLayout(self.image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.addWidget(self.image_label, alignment=Qt.AlignCenter)
        self.stack.addWidget(self.image_page)

        # start checking
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_image)
        self.check_timer.start(2000)
        self.check_image()

    def check_image(self):
        if QFile.exists(str(self.image_path)):
            self.check_timer.stop()
            self.pixmap = QPixmap(str(self.image_path))
            self.updatePixmap()
            self.stack.setCurrentIndex(1)

    def updatePixmap(self):
        if not self.pixmap:
            return
        
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaledToWidth(
                        self.width(),
                        Qt.SmoothTransformation
                    )
            self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        self.updatePixmap()

    def mousePressEvent(self, event):
        if QFile.exists(str(self.image_path)):
            ImageOverlay.open(self.image_path)
        super().mousePressEvent(event)
