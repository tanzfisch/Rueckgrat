import asyncio
from typing import Optional

import flet as ft

from app.common import get_logger
from .hub import Hub
from .notifier import Notifier
logger = get_logger()

try:  # only bundled into the Android build (see pyproject.toml), absent on desktop
    from flet_foreground_service import ForegroundService
except ImportError:
    ForegroundService = None

TITLE = "Rückgrat"


class KeepAlive:
    """
    Keeps the hub connection while the app is in the background.

    Android freezes an app a few seconds after it leaves the screen (and silences its mic) unless it runs a
    foreground service. It runs while logged in (type specialUse, "Connected"), plus type microphone while
    recording. The OS only lets it start or gain a type while the app is visible, so a change made in the
    background waits for the next resume. Stopping works any time.

    All platforms: back in front, a hub socket that died meanwhile is replaced at once (Hub.check_connection).
    """
    _page = None
    _service = None                 # ForegroundService, Android only
    _visible = True
    _logged_in = False
    _microphone = False
    _types: tuple[str, ...] = ()    # of the running service
    _lock: Optional[asyncio.Lock] = None

    @classmethod
    def attach(cls, page: ft.Page):
        cls._page = page
        Notifier.register_lifecycle(cls._on_lifecycle)
        Hub.register_session_change(cls._on_session)
        if ForegroundService is not None and page.platform == ft.PagePlatform.ANDROID:
            cls._service = ForegroundService()
            page.services.append(cls._service)
            page.update()

    @classmethod
    async def set_microphone(cls, on: bool):
        """recording on / off. on: call it while visible and after RECORD_AUDIO is granted (Android 14+). never raises"""
        cls._microphone = on
        await cls._apply()

    @classmethod
    def _on_lifecycle(cls, state: ft.AppLifecycleState):
        cls._visible = state == ft.AppLifecycleState.RESUME
        if cls._visible:
            cls._page.run_task(cls._on_resume)

    @classmethod
    async def _on_resume(cls):
        await cls._apply()
        await Hub.check_connection()

    @classmethod
    def _on_session(cls, logged_in: bool):
        if logged_in != cls._logged_in and cls._page is not None:
            cls._logged_in = logged_in
            cls._page.run_task(cls._apply)

    @classmethod
    def _wanted(cls) -> tuple[str, ...]:
        return ("specialUse",) * cls._logged_in + ("microphone",) * cls._microphone

    @classmethod
    async def _apply(cls):
        """brings the service to _wanted(), one change at a time"""
        if cls._service is None:
            return
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            types = cls._wanted()
            if types == cls._types:
                return
            try:
                if not types:
                    await cls._service.stop()
                    cls._types = ()
                elif not cls._visible:
                    logger.info(f"foreground service {types} waits until the app is in front")
                elif await cls._service.start(TITLE, "Microphone active" if cls._microphone else "Connected", list(types)):
                    cls._types = types
                else:
                    logger.warning(f"foreground service {types} did not start, the app disconnects in the background")
            except Exception as e:
                logger.warning(f"foreground service {types} failed: {e!r}")
