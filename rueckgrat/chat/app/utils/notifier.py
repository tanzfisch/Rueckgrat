import shutil
import subprocess
import threading

import flet as ft

from app.common import get_logger
logger = get_logger()

try:  # only bundled into the Android build (see pyproject.toml), absent on desktop
    from flet_notifications import Notifications
except ImportError:
    Notifications = None

APP_NAME = "Rückgrat"
BODY_LENGTH = 120


class Notifier:
    """
    System notifications for "reply finished" and "image ready", only while the app is not in front.

    Android: the local extension flet_notifications. Linux: org.freedesktop.Notifications over D-Bus
    with gdbus (part of glib, no python dependency). Other platforms: logged only.
    """
    _page = None
    _android = None    # Notifications service
    _active = True     # app in front with input focus, driven by on_app_lifecycle_state_change

    @classmethod
    def attach(cls, page: ft.Page):
        cls._page = page
        page.on_app_lifecycle_state_change = cls._on_lifecycle
        if Notifications is not None and page.platform == ft.PagePlatform.ANDROID:
            cls._android = Notifications()
            page.services.append(cls._android)
            page.update()
            page.run_task(cls._request_permission)

    @classmethod
    def _on_lifecycle(cls, e: ft.AppLifecycleStateChangeEvent):
        cls._active = e.state == ft.AppLifecycleState.RESUME

    @classmethod
    async def _request_permission(cls):
        try:
            await cls._android.request_permission()
        except Exception as e:
            logger.warning("notification permission request failed: %r", e)

    @classmethod
    def notify(cls, title: str, body: str):
        """ thread safe, never raises. does nothing while the user looks at the app """
        if cls._active or cls._page is None:
            return
        body = " ".join(body.split())
        if len(body) > BODY_LENGTH:
            body = body[:BODY_LENGTH - 1] + "…"
        if cls._android is not None:
            cls._page.run_task(cls._show_android, title, body)
        elif cls._page.platform == ft.PagePlatform.LINUX:
            threading.Thread(target=cls._show_linux, args=(title, body), daemon=True).start()
        else:
            logger.debug(f"no notifications on {cls._page.platform}: {title}")

    @classmethod
    async def _show_android(cls, title: str, body: str):
        try:
            if not await cls._android.show(title, body):
                logger.info("notification not shown, permission missing")
        except Exception as e:
            logger.warning("notification failed: %r", e)

    @staticmethod
    def _gvariant_string(text: str) -> str:
        return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"

    @classmethod
    def _show_linux(cls, title: str, body: str):
        gdbus = shutil.which("gdbus")
        if gdbus is None:
            logger.info("no notification: gdbus not found")
            return
        # Notify(app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout)
        args = [gdbus, "call", "--session",
                "--dest", "org.freedesktop.Notifications",
                "--object-path", "/org/freedesktop/Notifications",
                "--method", "org.freedesktop.Notifications.Notify",
                cls._gvariant_string(APP_NAME), "0", "''",
                cls._gvariant_string(title), cls._gvariant_string(body), "[]", "{}", "-1"]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                logger.info(f"no notification: {result.stderr.strip()}")
        except Exception as e:
            logger.info(f"no notification: {e!r}")
