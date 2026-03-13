import sys
import truststore
from pathlib import Path
import qasync
import asyncio
from qasync import QApplication
from PySide6.QtWidgets import (QStackedWidget, QMainWindow)
import atexit
from app.utils.backend import backend

from app.ui import LoginPage, ChatPage, ContactsPage, ConversationsPage, ProfilePage
from app.speech import Speech

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
    asyncio.create_task(backend.start_websocket())

    await asyncio.Event().wait()  # keep loop alive


def main():
    truststore.inject_into_ssl()
    atexit.register(Speech.kill_current_speech)

    app = qasync.QApplication(sys.argv)

    qss_path = Path(__file__).parent / "style.qss"
    with open(qss_path) as f:
        app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()

    qasync.run(async_main(app, window))

if __name__ == "__main__":
    main()