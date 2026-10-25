import flet as ft

__all__ = ["Notifications"]


@ft.control("Notifications")
class Notifications(ft.Service):
    """
    Plain Android notifications in the channel "rueckgrat_events". A tap opens the app.

    Add it to `page.services`. Android only, every call answers False elsewhere.
    """

    async def request_permission(self, timeout: float = 10) -> bool:
        """Android 13+: asks for POST_NOTIFICATIONS (does not wait for the answer). True if already granted."""
        return bool(await self._invoke_method("request_permission", timeout=timeout))

    async def show(self, title: str, body: str, timeout: float = 10) -> bool:
        """True if the notification was posted, False without the permission."""
        return bool(await self._invoke_method("show", {"title": title, "body": body}, timeout=timeout))
