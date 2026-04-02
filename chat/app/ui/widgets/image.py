from PySide6.QtWidgets import QLabel
from PySide6.QtCore import QTimer, QFile
from PySide6.QtGui import QPixmap, QMovie

class Image(QLabel):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path

        # Force fixed size and cache the original
        movie = QMovie("app/icons/loading.gif")
        self.setFixedSize(128, 128)

        self.setMovie(movie)
        movie.start()

        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_image)
        self.check_timer.start(10000)

    def check_image(self):
        if QFile.exists(self.image_path):
            self.timer.stop()
            self.check_timer.stop()
            self.setPixmap(QPixmap(self.image_path))