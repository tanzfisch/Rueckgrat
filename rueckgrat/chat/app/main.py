import sys
import truststore
from pathlib import Path
import qasync
import asyncio
from qasync import QApplication
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout)
from PySide6.QtCore import QTimer
import atexit
from app.ui import LoginPage, ChatPage, ContactsPage, ConversationsPage, ProfilePage, ProfileWizard, SettingsPage, InitialSettingsPage
from app.speech import Speech
from app.utils.hub import Hub
from app.utils.config import RueckgratConfig
from app.utils import Paths
import platform

from app.common import get_logger, Utils
logger = get_logger()

class MainWindow(QMainWindow):
    def __init__(self, hasConfig: bool):
        super().__init__()
        self.resize(600, 1200)

        central = QWidget()
        self.main_layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        self.center_on_screen()

        self.current_page = None

        if hasConfig:
            self.navigate("login")
        else:
            self.navigate("initial_settings")

        self.heartbeat_timer = QTimer()
        self.heartbeat_timer.timeout.connect(self.heartbeat)
        self.heartbeat_timer.setInterval(10000)
        self.heartbeat_timer.start()        

    def create_page(self, name: str):
        if name == "login": 
            return LoginPage(self.navigate)
        if name == "chat":
            return ChatPage(self.navigate)
        if name == "contacts": 
            return ContactsPage(self.navigate)
        if name == "conversations": 
            return ConversationsPage(self.navigate)
        if name == "profile":
            return ProfilePage(self.navigate)
        if name == "profile_wizz": 
            return ProfileWizard(self.navigate)    
        if name == "settings": 
            return SettingsPage(self.navigate)    
        if name == "initial_settings":
            return InitialSettingsPage(self.navigate)    

    def heartbeat(self):
        if not Hub.check_health():
            logger.error("system unhealthy")

    def navigate(self, page_name: str, **kwargs):
        if self.current_page:
            self.current_page.on_leave()
            self.main_layout.removeWidget(self.current_page)
            self.current_page.deleteLater()
            self.current_page = None

        self.current_page = self.create_page(page_name)
        self.main_layout.addWidget(self.current_page)
        self.current_page.on_enter(**kwargs)

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        center = screen.availableGeometry().center()
        geo = self.frameGeometry()
        geo.moveCenter(center)
        self.move(geo.topLeft())

async def async_main(app, window):
    stop_event = asyncio.Event()
    app.aboutToQuit.connect(stop_event.set)
    await stop_event.wait()

    await Hub.stop_websocket()

def get_image(image_filename: str) -> str:
    if not image_filename:
        logger.error(f"invalid parameter: {image_filename}")
        return
    
    try:
        logger.debug(f"image_filename {image_filename}")
        image_path = Paths.get_image_path() / image_filename
        logger.debug(f"image_path {image_path}")
        logger.debug(f"check {image_path}")
        if not image_path.exists():
            logger.debug(f"download {image_path}")
            Hub.download_file(f"images/{image_filename}", Paths.get_image_path())
    except Exception as e:
        logger.error(f"failed to handle incomming image: {repr(e)}")

def on_incomming_message(msg: dict):
    try:
        if "image" in msg:
            image = msg["image"]
            filename = image["filename"]
            if filename:
                get_image(image["filename"])

        if "error" in msg:
            error = msg["error"]
            logger.error(f"[{error["src"]}] {error["msg"]}")

        if "warning" in msg:
            warning = msg["warning"]
            logger.warning(f"[{warning["src"]}] {warning["msg"]}")

    except Exception as e:
        logger.error(f"failed to handle incomming message {e}")

def main():
    logger.debug(f"platform: {platform.system()}{' (inside docker)' if Utils.is_docker() else ''}")
    
    config = RueckgratConfig()
    Hub.init(config)

    truststore.inject_into_ssl()
    atexit.register(Speech.kill_current_speech)
    atexit.register(Hub.shutdown)

    app = qasync.QApplication(sys.argv)

    qss_path = Path(__file__).parent / "style.qss"
    with open(qss_path) as f:
        app.setStyleSheet(f.read())

    window = MainWindow(config.has_config())
    window.show()

    Hub.register_incomming_message(on_incomming_message)

    qasync.run(async_main(app, window))

    Hub.unregister_incomming_message(on_incomming_message)

if __name__ == "__main__":
    main()