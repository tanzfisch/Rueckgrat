import flet as ft

__all__ = ["ForegroundService"]


@ft.control("ForegroundService")
class ForegroundService(ft.Service):
    """
    Android foreground service, shown as a persistent notification.

    Without it Android freezes the app (network sockets drop) and silences the microphone
    a few seconds after it leaves the foreground (home button, screen lock).

    Add it to `page.services` and call `start()` while the app is visible, e.g. from a
    button click. Android only.
    """

    async def start(self, title: str, text: str, types: list[str], timeout: float = 60) -> bool:
        """Ask for the notification permission if needed, then start the service with the given types
        ("specialUse", "microphone", each needs its FOREGROUND_SERVICE_* permission and must be in the
        manifest). Running with other types: restarted with these. True if it runs."""
        return bool(await self._invoke_method("start", {"title": title, "text": text, "types": types}, timeout=timeout))

    async def stop(self, timeout: float = 10) -> None:
        await self._invoke_method("stop", timeout=timeout)
