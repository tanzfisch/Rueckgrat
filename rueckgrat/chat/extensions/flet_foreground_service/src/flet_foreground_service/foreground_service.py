import flet as ft

__all__ = ["ForegroundService"]


@ft.control("ForegroundService")
class ForegroundService(ft.Service):
    """
    Android foreground service of type `microphone`, shown as a persistent notification.

    Without it Android silences the microphone and kills the network sockets of the app
    a few seconds after it leaves the foreground (home button, screen lock).

    Add it to `page.services` and call `start()` while the app is visible, e.g. from a
    button click. Android only.
    """

    async def start(self, title: str, text: str, timeout: float = 60) -> bool:
        """Ask for the notification permission if needed, then start the service. True if it runs."""
        return bool(await self._invoke_method("start", {"title": title, "text": text}, timeout=timeout))

    async def stop(self, timeout: float = 10) -> None:
        await self._invoke_method("stop", timeout=timeout)
