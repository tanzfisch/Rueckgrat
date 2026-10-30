import asyncio
import sys
import time
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
    TranslatePage,
    ImagePage,
    GalleryPage,
)
from app.ui.theme import apply_theme
from app.ui.widgets import ImageOverlay, MessageBox, ConnectionBanner

from app.utils import Paths, Notifier
from app.utils.config import RueckgratConfig
from app.utils.hub import Hub

from app.common import get_logger, set_log_level, Utils
logger = get_logger()

TOKEN_REFRESH_SECONDS = 45 * 60

PAGES = {
    "login": LoginPage,
    "contacts": ContactsPage,
    "conversations": ConversationsPage,
    "chat": ChatPage,
    "profile": ProfilePage,
    "profile_wizz": ProfileWizard,
    "settings": SettingsPage,
    "initial_settings": InitialSettingsPage,
    "translate": TranslatePage,
    "image": ImagePage,
    "gallery": GalleryPage,
}
ROOT_PAGES = {"login", "initial_settings", "contacts"}   # opening one of these starts the back stack anew
MAX_STACK = 20


class Navigator:
    """what the pages get: navigator("chat", contact_id=1) opens a page, navigator.back() returns to the one before"""

    def __init__(self, navigate, back):
        self._navigate = navigate
        self.back = back

    def __call__(self, page_name: str, **kwargs):
        self._navigate(page_name, **kwargs)


class App:
    def __init__(self, page: ft.Page, has_config: bool):
        self.page = page
        self.current_page = None
        self._current_name = None
        self._stack: list[tuple[str, dict]] = []   # (page name, kwargs) of every page on the way here, the last is shown
        self.navigator = Navigator(self.navigate, self.back)

        page.title = "Rueckgrat"
        page.window.width = 600
        page.window.height = 1200
        page.run_task(page.window.center)
        page.padding = 0

        page.on_route_change = self._on_route_change
        if not page.web and sys.platform not in ("android", "ios"):
            # desktop: closing the window asks first, like back on the last page
            page.window.prevent_close = True
            page.window.on_event = self._on_window_event
        page.on_disconnect = self._on_disconnect

        # hub connection lost / back, shown above every page
        self.connection_banner = ConnectionBanner()
        page.overlay.append(self.connection_banner)
        Hub.register_connection_state(self._on_connection_state)

        if has_config and Hub.has_stored_session():
            page.run_task(self._restore_session)
        else:
            self.navigate("login" if has_config else "initial_settings")
        page.run_task(self._heartbeat_loop)

    def navigate(self, page_name: str, **kwargs):
        if page_name in ROOT_PAGES:
            self._stack.clear()
        if self._stack and self._stack[-1][0] == page_name:
            self._stack.pop()     # the same page again (e.g. another conversation): replace it, no duplicate
        self._stack.append((page_name, kwargs))
        del self._stack[:-MAX_STACK]
        self._go(page_name)

    def back(self) -> bool:
        """to the page before, with the kwargs it had. False if there is none"""
        if len(self._stack) < 2:
            return False
        self._stack.pop()
        self._go(self._stack[-1][0])
        return True

    def _go(self, page_name: str):
        if page_name == self._current_name:
            self._show(page_name)   # the route doesn't change, so no route change event: rebuild here
        else:
            self.page.navigate(f"/{page_name}")

    def create_page(self, name: str):
        cls = PAGES.get(name)
        if cls is None:
            raise ValueError(f"unknown page: {name}")
        return cls(self.navigator)

    def _on_route_change(self, e: ft.RouteChangeEvent):
        name = e.route.strip("/").split("?")[0] or "login"
        if name not in PAGES:
            name = "login"
        if not self._stack or self._stack[-1][0] != name:
            # the route changed without navigate(): browser back/forward or a typed url (web)
            if len(self._stack) >= 2 and self._stack[-2][0] == name:
                self._stack.pop()
            else:
                if name in ROOT_PAGES:
                    self._stack.clear()
                self._stack.append((name, {}))
        self._show(name)

    def _show(self, name: str):
        if self.current_page:
            self.current_page.on_leave()

        self._current_name = name
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

        # android system back button handler
        view.can_pop = False
        view.on_confirm_pop = self._on_system_back

        self.page.views.clear()
        self.page.views.append(view)
        self.page.update()
        self.current_page.on_enter(**self._stack[-1][1])

    def _header_go_back(self):
        """the back handler of the current page's header, None if it has no visible back button"""
        header = getattr(self.current_page, "header", None)
        if header is None or header.back_btn not in header.controls or not header.back_btn.visible:
            return None
        return header.on_go_back

    async def _on_system_back(self, e):
        view = e.control
        # back closes the full screen image first, then goes back a page
        if ImageOverlay.close_open(self.page):
            await view.confirm_pop(False)
            return
        go_back = self._header_go_back()
        if go_back and len(self._stack) >= 2:
            await view.confirm_pop(False)
            go_back()
            return
        # the last page of the stack: the pop stays pending until the user answers, ok exits the app
        self._confirm_exit(lambda ok: self.page.run_task(view.confirm_pop, ok))

    def _on_window_event(self, e: ft.WindowEvent):
        if e.type == ft.WindowEventType.CLOSE:
            self._confirm_exit(lambda ok: ok and self.page.run_task(self._destroy_window))

    async def _destroy_window(self):
        try:
            await self.page.window.destroy()
        except RuntimeError:
            pass    # the window is gone before flet gets its answer ("Session closed")

    def _confirm_exit(self, on_result):
        """the only way out of the app: on_result(True) once the user confirmed, False if not"""
        MessageBox.show(self.page, "Do you want to close Rueckgrat?", kind="question", ok_text="Exit", on_result=on_result)

    def _on_connection_state(self, state: str):
        self.connection_banner.on_state(self.page, state)
        if state == "rejected":
            self.page.run_task(self._session_expired)

    async def _restore_session(self):
        """stay logged in after a restart. hub not reachable: contacts anyway, the banner shows it and the heartbeat retries"""
        restored = await Hub.refresh_session()
        self.navigate("login" if restored is False else "contacts")

    async def _session_expired(self):
        # the access token ran out: a stored session gets new tokens, only a refused one logs out
        restored = await Hub.refresh_session()
        if restored is not False:
            return
        await Hub.logout()
        self.navigate("login")
        MessageBox.error(self.page, "your session has expired, please log in again", title="Logged out")

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(10)
            Hub.check_health()
            # new tokens well before the hub's 60 minutes, or as soon as the hub is back after a failed restore
            if Hub.refresh_token and (not Hub.access_token or time.time() - Hub.token_time > TOKEN_REFRESH_SECONDS):
                if await Hub.refresh_session() is False:
                    await self._session_expired()

    async def _on_disconnect(self, e):
        await Hub.stop_websocket()


def get_image(image_filename: str) -> str:
    if not image_filename:
        logger.error(f"invalid parameter: {image_filename}")
        return
    try:
        image_path = Paths.get_image_path() / image_filename
        if not image_path.exists():
            Hub.download_file(f"images/{image_filename}", Paths.get_image_path(),
                              callback=lambda: Notifier.notify("Image ready", "A new image was generated"))
    except Exception as e:
        logger.error(f"failed to handle incomming image: {repr(e)}")


def on_incomming_message(msg: dict):
    try:
        if "image" in msg:
            filename = msg["image"].get("filename")
            if filename:
                get_image(filename)
        if "generated_image" in msg:   # result of the image page
            filename = msg["generated_image"].get("filename")
            if filename:
                get_image(filename)
        if "chat" in msg and msg["chat"].get("role") == "assistant":
            Notifier.notify("Reply ready", msg["chat"].get("content", ""))
        if "error" in msg:
            error = msg["error"]
            logger.error(f"[{error['src']}] {error['msg']}")
        if "warning" in msg:
            warning = msg["warning"]
            logger.warning(f"[{warning['src']}] {warning['msg']}")
    except Exception as e:
        logger.error(f"failed to handle incomming message: {e}")


def main():
    config = RueckgratConfig()
    set_log_level(config.log_level)

    logger.debug(
        f"platform: {platform.system()}"
    )

    Hub.init(config)

    if sys.platform != "android":
        atexit.register(Text_To_Speech.kill_current_speech)
        atexit.register(Hub.shutdown)

    Hub.register_incomming_message(on_incomming_message)

    def flet_main(page: ft.Page):
        apply_theme(page)
        Text_To_Speech.attach(page)
        Notifier.attach(page)
        page.padding = 0
        App(page, config.has_config())

    ft.run(flet_main)
    Hub.unregister_incomming_message(on_incomming_message)


if __name__ == "__main__":
    main()