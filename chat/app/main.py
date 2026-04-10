import sys
import truststore
from pathlib import Path
import qasync
import asyncio
from qasync import QApplication
from PySide6.QtWidgets import (QStackedWidget, QMainWindow)
from PySide6.QtCore import QTimer
import atexit
from app.ui import LoginPage, ChatPage, ContactsPage, ConversationsPage, ProfilePage
from app.speech import Speech
from app.utils.backend import Backend

from common import Logger
logger = Logger(__name__).get_logger()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.resize(600, 1200)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Create pages and store them in a dict
        self.pages = {}
        self.current_page = None

        self.pages["login"] = LoginPage(self.navigate)
        self.pages["chat"] = ChatPage(self.navigate)
        self.pages["contacts"] = ContactsPage(self.navigate)
        self.pages["conversations"] = ConversationsPage(self.navigate)
        self.pages["profile"] = ProfilePage(self.navigate)

        for page in self.pages.values():
            self.stack.addWidget(page)

        self.navigate("login")

        self.center_on_screen()

        self.heartbeat_timer = QTimer()
        self.heartbeat_timer.timeout.connect(self.heartbeat)
        self.heartbeat_timer.setInterval(10000)
        self.heartbeat_timer.start()        

    def heartbeat(self):
        if not Backend.get_instance().check_health():
            logger.error("system unhealthy")

    def navigate(self, page_name, **kwargs):
        if self.current_page:
            self.current_page.on_leave()

        self.current_page = self.pages[page_name]
        self.stack.setCurrentWidget(self.current_page)
        self.current_page.on_enter(**kwargs)

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        center = screen.availableGeometry().center()
        geo = self.frameGeometry()
        geo.moveCenter(center)
        self.move(geo.topLeft())

async def async_main(app, window):
    ws_task = asyncio.create_task(Backend.get_instance().start_websocket())

    stop_event = asyncio.Event()
    app.aboutToQuit.connect(stop_event.set)

    await stop_event.wait()

    ws_task.cancel()
    try:
        await ws_task
    except asyncio.CancelledError:
        pass

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

    qasync.run(async_main(app, window))

if __name__ == "__main__":
    main()