import os
import flet as ft
from urllib.parse import urlparse

from app.common import get_logger
logger = get_logger()

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"


class StatusWidget(ft.Row):
    def __init__(self, **kwargs):
        self.gif = ft.Image(src=f"{ASSETS_DIR}/icons/loading.gif", width=20, height=20, visible=False)
        self.label = ft.Text("", visible=False)
        self.btn_row = ft.Row(spacing=0)
        super().__init__(
            controls=[self.gif, self.label, self.btn_row, ft.Container(expand=True)],
            spacing=10,
            visible=False,
            **kwargs,
        )

    def clear_urls(self):
        self.btn_row.controls.clear()

    def _sync(self):
        try:
            self.update()
        except RuntimeError:
            pass

    def clear_status(self):
        self.stop_waiting()
        self.set_text("")
        self.visible = False
        self.clear_urls()
        self._sync()

    def on_status_message(self, status: dict):
        if "message" in status:
            self.set_text(status["message"])
            self.start_waiting()
        if "url" in status:
            self.add_url_button(status["url"])
        if status.get("state") == "reset":
            self.clear_status()
            return
        if status.get("state") == "done":
            self.stop_waiting()
            self.label.visible = False
        self._sync()

    def set_text(self, text):
        self.label.value = text
        self.label.visible = bool(text)
        self.visible = True

    def start_waiting(self):
        self.gif.visible = True
        self.visible = True

    def stop_waiting(self):
        self.gif.visible = False

    def add_url_button(self, url: str):
        try:
            parsed = urlparse(url if "://" in url else f"https://{url}")
            domain = parsed.netloc.removeprefix("www.")
            href = parsed.geturl()
            btn = ft.IconButton(
                content=ft.Image(
                    src=f"https://www.google.com/s2/favicons?domain={domain}",
                    width=16,
                    height=16,
                ),
                tooltip=url,
                width=20,
                height=20,
                data={"id": "flatButton"},
                on_click=lambda e, u=href: e.page.launch_url(u),
            )
            self.btn_row.controls.append(btn)
            logger.debug(f"Added button for {domain}")
        except Exception as e:
            logger.warning(f"Failed to add button for {url}: {e}")