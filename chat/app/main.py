import sys
import truststore
from pathlib import Path
import qasync
import asyncio
from qasync import QApplication
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout)
from PySide6.QtCore import QTimer
import atexit
from app.ui import LoginPage, ChatPage, ContactsPage, ConversationsPage, ProfilePage, ProfileWizard
from app.speech import Speech
from app.utils.backend import Backend

from common import Logger
logger = Logger(__name__).get_logger()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.resize(600, 1200)

        central = QWidget()
        self.main_layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        self.current_page = None

        self.navigate("login")

        self.center_on_screen()

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

    def heartbeat(self):
        if not Backend.get_instance().check_health():
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
    #ws_task = asyncio.create_task(Backend.get_instance().start_websocket())

    stop_event = asyncio.Event()
    app.aboutToQuit.connect(stop_event.set)

    await stop_event.wait()

    #ws_task.cancel()
    #try:
    #    await ws_task
    #except asyncio.CancelledError:
    #    pass

    Backend.get_instance().stop_websocket()

def get_image(image_filename) -> str:
    try:
        image_path = Path("cache/images") / image_filename
        logger.debug(f"check {image_path}")
        if not image_path.exists():
            logger.debug(f"download {image_path}")
            Backend.get_instance().download(f"images/{image_filename}", "cache/images")
    except Exception as e:
        logger.error(f"failed to handle incomming image: {repr(e)}")

def on_incomming_message(msg: dict):
    if "image" in msg:
        image = msg["image"]
        get_image(image["filename"])

def main():
    truststore.inject_into_ssl()
    atexit.register(Speech.kill_current_speech)
    atexit.register(Backend.get_instance().shutdown)

    app = qasync.QApplication(sys.argv)

    qss_path = Path(__file__).parent / "style.qss"
    with open(qss_path) as f:
        app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()

    Backend.get_instance().register_incomming_message(on_incomming_message)

    qasync.run(async_main(app, window))

    Backend.get_instance().unregister_incomming_message(on_incomming_message)

if __name__ == "__main__":
    main()