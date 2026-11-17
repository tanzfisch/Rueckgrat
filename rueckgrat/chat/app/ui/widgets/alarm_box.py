import flet as ft

from .message_box import MessageBox
from app.utils import Alarm, Notifier
from app.common import get_logger

logger = get_logger()


class AlarmBox:
    """#170 a task with its alarm is done: a notification (also while the app is in front), the ring and a box with the
    message, its Stop button ends the ring"""
    _page = None

    @classmethod
    def attach(cls, page: ft.Page):
        cls._page = page
        Alarm.attach(page)

    @classmethod
    def show(cls, text: str, name: str = ""):
        """thread safe (the hub's push comes on the websocket's thread), never raises"""
        title = f"⏰ {name}" if name else "⏰ Alarm"
        Notifier.notify(title, text, always=True)
        Alarm.ring()
        if cls._page is None:
            return

        async def show_box():
            MessageBox.show(cls._page, text, title=title, kind="info", ok_text="Stop", on_result=lambda ok: Alarm.stop())

        try:
            cls._page.run_task(show_box)
        except Exception as e:
            logger.error(f"alarm box not shown {e!r}")
