import asyncio
import flet as ft

from app.ui.theme import ERROR, TEAL_FILL, TEXT


class ConnectionBanner(ft.SafeArea):
    """app wide strip at the top (lives in page.overlay): red while the hub connection is lost,
    briefly green once it is back. fed by Hub.register_connection_state"""
    SHOW_AFTER = 2  # s, short drops (flapping) show nothing
    HIDE_AFTER = 1  # s the green "reconnected" stays

    def __init__(self):
        self._lost = False
        self._gen = 0  # bumped on every state change, so older timers can't override a newer state
        self._page = None
        self.icon = ft.Icon(ft.Icons.CLOUD_OFF, color=TEXT, size=18)
        self.text = ft.Text("", color=TEXT)
        self.strip = ft.Container(
            padding=8,
            content=ft.Row([self.icon, self.text], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
        )
        super().__init__(left=0, top=0, right=0, visible=False, content=self.strip)

    def on_state(self, page: ft.Page, state: str):
        self._page = page
        self._gen += 1
        was_visible = self.visible
        self._lost = state == "lost"
        if self._lost:
            page.run_task(self._show_lost, self._gen)
        elif state == "reconnected" and was_visible:
            # the red strip goes away right now, the green one only stays for HIDE_AFTER
            self._set(True, ft.Icons.CLOUD_DONE, "reconnected", TEAL_FILL)
            page.run_task(self._hide_later, self._gen)
        else:
            self._set(False)

    async def _show_lost(self, gen: int):
        await asyncio.sleep(self.SHOW_AFTER)
        if gen == self._gen:
            self._set(True, ft.Icons.CLOUD_OFF, "connection lost, reconnecting…", ERROR)

    async def _hide_later(self, gen: int):
        await asyncio.sleep(self.HIDE_AFTER)
        if gen == self._gen:
            self._set(False)

    def _set(self, visible: bool, icon=None, text: str = "", color=None):
        self.visible = visible
        if visible:
            self.icon.icon = icon
            self.text.value = text
            self.strip.bgcolor = color
        try:
            self.update()
        except RuntimeError:
            if self._page:
                self._page.update()  # not mounted as expected, push the whole page instead
