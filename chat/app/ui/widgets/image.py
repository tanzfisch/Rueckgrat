from PySide6.QtWidgets import QLabel
from PySide6.QtCore import QTimer, QFile, Qt
from PySide6.QtGui import QPixmap, QMovie
from pathlib import Path

from common import Logger
logger = Logger(__name__).get_logger()

class Image(QLabel):
    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.pixmap = None

        movie = QMovie("app/icons/loading.gif")
        self.setMovie(movie)
        movie.start()

        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_image)
        self.check_timer.start(2000)
        self.check_image()

    def check_image(self):
        if QFile.exists(str(self.image_path)):
            self.check_timer.stop()
            self.pixmap = QPixmap(str(self.image_path))
            self.updatePixmap()

    def updatePixmap(self):
        if not self.pixmap:
            return
        
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaledToWidth(
                        self.width(),
                        Qt.SmoothTransformation
                    )
            self.setPixmap(scaled)

    def resizeEvent(self, event):
        self.updatePixmap()