import os
import flet as ft

from app.common import get_logger
logger = get_logger()

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"


class StatusWidget(ft.Row):
    def __init__(self, **kwargs):
        self.gif = ft.Image(src=f"{ASSETS_DIR}/icons/loading.gif", width=20, height=20, visible=False)
        self.label = ft.Text("", visible=False)
        super().__init__(
            controls=[self.gif, self.label, ft.Container(expand=True)],
            spacing=10,
            visible=False,
            **kwargs,
        )

    def _sync(self):
        try:
            self.update()
        except RuntimeError:
            pass

    def clear_status(self):
        self.stop_waiting()
        self.set_text("")
        self.visible = False
        self._sync()

    def on_status_message(self, status: dict):
        if "message" in status:
            self.set_text(status["message"])
            self.start_waiting()
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
