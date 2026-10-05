import asyncio
import sys
import atexit
import platform
from urllib.parse import parse_qs, urlparse
import flet as ft

from app.audio import Text_To_Speech
from app.utils.hub import Hub
from app.ui import (
    LoginPage,
    ContactsPage,
    ConversationsPage,
    ChatPage,
    ProfilePage,
    InitialSettingsPage,
    ProfileWizard,
    SettingsPage,
)
from app.ui.theme import apply_theme

from app.utils import Paths
from app.utils.config import RueckgratConfig
from app.utils.hub import Hub

from app.common import get_logger, Utils
logger = get_logger()

PAGES = {
    "login": LoginPage,
    "contacts": ContactsPage,
    "conversations": ConversationsPage,
    "chat": ChatPage,
    "profile": ProfilePage,
    "profile_wizz": ProfileWizard,
    "settings": SettingsPage,
    "initial_settings": InitialSettingsPage,
}


class App:
    def __init__(self, page: ft.Page, has_config: bool):
        self.page = page
        self.current_page = None
        self._kwargs: dict = {}

        page.title = "Rueckgrat"
        page.window.width = 600
        page.window.height = 1200
        page.run_task(page.window.center)
        page.padding = 0

        page.on_route_change = self._on_route_change
        page.on_disconnect = self._on_disconnect

        start = "login" if has_config else "initial_settings"
        page.navigate(f"/{start}")
        page.run_task(self._heartbeat_loop)

    def navigate(self, page_name: str, **kwargs):
        self._kwargs = kwargs
        self.page.navigate(f"/{page_name}")

    def create_page(self, name: str):
        cls = PAGES.get(name)
        if cls is None:
            raise ValueError(f"unknown page: {name}")
        return cls(self.navigate)

    def _on_route_change(self, e: ft.RouteChangeEvent):
        name = e.route.strip("/").split("?")[0] or "login"
        if name not in PAGES:
            name = "login"

        if self.current_page:
            self.current_page.on_leave()

        self.current_page = self.create_page(name)
        view = getattr(self.current_page, "view", None)
        if view is None:
            view = ft.View(
                route=f"/{name}",
                padding=0,
                controls=[
                    ft.SafeArea(
                        expand=True,
                        avoid_intrusions_top=True,
                        avoid_intrusions_bottom=True,
                        maintain_bottom_view_padding=True,
                        content=self.current_page,
                    )
                ],
            )

        self.page.views.clear()
        self.page.views.append(view)
        self.page.update()
        self.current_page.on_enter(**self._kwargs)
        self._kwargs = {}

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(10)
            if not Hub.check_health():
                logger.error("system unhealthy")

    async def _on_disconnect(self, e):
        await Hub.stop_websocket()


def get_image(image_filename: str) -> str:
    if not image_filename:
        logger.error(f"invalid parameter: {image_filename}")
        return
    try:
        image_path = Paths.get_image_path() / image_filename
        if not image_path.exists():
            Hub.download_file(f"images/{image_filename}", Paths.get_image_path())
    except Exception as e:
        logger.error(f"failed to handle incomming image: {repr(e)}")


def on_incomming_message(msg: dict):
    try:
        if "image" in msg:
            filename = msg["image"].get("filename")
            if filename:
                get_image(filename)
        if "error" in msg:
            error = msg["error"]
            logger.error(f"[{error['src']}] {error['msg']}")
        if "warning" in msg:
            warning = msg["warning"]
            logger.warning(f"[{warning['src']}] {warning['msg']}")
    except Exception as e:
        logger.error(f"failed to handle incomming message: {e}")


def main():
    logger.debug(
        f"platform: {platform.system()}"
    )
    config = RueckgratConfig()
    Hub.init(config)

    if sys.platform != "android":
        atexit.register(Text_To_Speech.kill_current_speech)
        atexit.register(Hub.shutdown)

    Hub.register_incomming_message(on_incomming_message)

    def flet_main(page: ft.Page):
        apply_theme(page)
        page.padding = 0
        App(page, config.has_config())

    ft.run(flet_main)
    Hub.unregister_incomming_message(on_incomming_message)


if __name__ == "__main__":
    main()