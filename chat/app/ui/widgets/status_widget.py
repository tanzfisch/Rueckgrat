from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QPushButton
from PySide6.QtGui import QMovie, QPixmap, QDesktopServices, QIcon
from PySide6.QtCore import QUrl, QSize, Qt
import requests

from common import Logger
logger = Logger(__name__).get_logger()

class StatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0); 
        self.layout.setSpacing(10)
    
        self.btn_layout = QHBoxLayout()
        self.btn_layout.setSpacing(0)
        self.btn_layout.setAlignment(Qt.AlignRight)
        self.layout.addLayout(self.btn_layout)  

        self.label = QLabel()
        self.layout.addWidget(self.label)

        self.gif_label = QLabel()
        self.gif_label.setContentsMargins(0, 0, 0, 0)
        self.gif_label.setScaledContents(True)
        self.gif_label.hide()
        self.movie = QMovie()
        self.movie.setFileName("app/icons/loading.gif")
        self.movie.setSpeed(40)
        self.gif_label.setMovie(self.movie)
        self.layout.addWidget(self.gif_label)

        self.layout.addStretch()

    def clear_urls(self):
        while self.btn_layout.count():
            item = self.btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()        

    def clear_status(self):
        self.stop_waiting()
        self.set_text("")
        self.hide()
        self.clear_urls()

    def on_status_message(self, status: dict):
        if "message" in status:
            self.set_text(status["message"])            
            self.start_waiting()

        if "url" in status:
            url = status["url"]
            self.add_url_button(url)

        if "state" in status:
            if status["state"] == "reset":
                self.clear_status()
            elif status["state"] == "done":
                self.stop_waiting()
                self.label.hide()

    def set_text(self, text):
        self.label.setText(text)
        self.label.show()
        self.show()

    def start_waiting(self):
        self.movie.start()
        self.gif_label.show()

    def stop_waiting(self):
        self.gif_label.hide()

    def add_url_button(self, url):
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.netloc:
                parsed = urlparse('https://' + url)  # add scheme if missing
            
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            
            favicon_url = f"https://www.google.com/s2/favicons?domain={domain}"
            data = requests.get(favicon_url, timeout=3).content
            
            pix = QPixmap()
            if not pix.loadFromData(data) or pix.isNull():
                raise ValueError("Failed to load favicon")
            
            btn = QPushButton()
            btn.setObjectName("flatButton")
            btn.setToolTip(url)
            btn.setIcon(QIcon(pix))
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(20, 20)
            btn.setFlat(True)
            btn.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            self.btn_layout.addWidget(btn)
            logger.debug(f"Added button for {domain}")
        except Exception as e:
            logger.warning(f"Failed to add button for {url}: {e}")