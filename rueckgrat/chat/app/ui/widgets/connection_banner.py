import asyncio
import flet as ft

from app.ui import theme
from app.utils.capabilities import Capabilities

# a missing capability in the banner: its icon and the name in its tooltip ("... unavailable")
SERVICE_ICONS = {
    "llm": (ft.Icons.SMART_TOY_OUTLINED, "Language model (llama.cpp)"),
    "tts": (ft.Icons.VOLUME_OFF, "Speech output (Chatterbox)"),
    "stt": (ft.Icons.MIC_OFF, "Speech recognition (faster-whisper)"),
    "image": (ft.Icons.HIDE_IMAGE, "Image generation"),
    "decision": (ft.Icons.ALT_ROUTE, "Decisions (Laya)"),
    "embedding": (ft.Icons.MEMORY, "Memory search (embeddings)"),
    "internet": (ft.Icons.PUBLIC_OFF, "Internet"),
    "library": (ft.Icons.LOCAL_LIBRARY_OUTLINED, "Offline library (Project NOMAD)"),
    "offline_map": (ft.Icons.MAP_OUTLINED, "Offline map (Project NOMAD)"),
}


class ConnectionBanner(ft.SafeArea):
    """app wide strip at the top (lives in page.overlay), see-through and click-through (the header's buttons under it
    still work, the icons' tooltips do not show): red while the hub connection is lost,
    briefly green once it is back. fed by Hub.register_connection_state.
    while the hub is connected it also shows a small icon per service the system is set up for but that is not available
    now (Capabilities.missing, live through Capabilities.listen), its name in the icon's tooltip. a service that is not
    installed shows nothing, with nothing missing and the connection fine the strip is hidden"""
    SHOW_AFTER = 2  # s, short drops (flapping) show nothing
    HIDE_AFTER = 1  # s the green "reconnected" stays
    OPACITY = 0.65  # of the strip's colour, what is under it shows through

    def __init__(self):
        self._lost = False
        self._gen = 0  # bumped on every state change, so older timers can't override a newer state
        self._page = None
        self._connection = None     # (icon, text, color) of the connection state shown, None: nothing to say about it
        self.icon = ft.Icon(ft.Icons.CLOUD_OFF, color=theme.ON_ACCENT, size=18)
        self.text = ft.Text("", color=theme.ON_ACCENT)
        self.missing = ft.Row(spacing=6, tight=True, visible=False)
        self.strip = ft.Container(
            padding=8,
            ignore_interactions=True,     # taps and clicks go to the controls under the strip
            content=ft.Row([self.icon, self.text, self.missing], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
        )
        super().__init__(left=0, top=0, right=0, visible=False, content=self.strip)
        Capabilities.listen(self.on_capabilities)    # the banner lives as long as the app

    def on_state(self, page: ft.Page, state: str):
        self._page = page
        self._gen += 1
        was_visible = self._connection is not None
        self._lost = state == "lost"
        if self._lost:
            self._set(False)    # the missing services are not known while the hub is gone
            page.run_task(self._show_lost, self._gen)
        elif state == "reconnected" and was_visible:
            # the red strip goes away right now, the green one only stays for HIDE_AFTER
            self._set(True, ft.Icons.CLOUD_DONE, "reconnected", theme.TEAL_FILL)
            page.run_task(self._hide_later, self._gen)
        else:
            self._set(False)

    def on_capabilities(self, lost: set = None):
        self._render()

    async def _show_lost(self, gen: int):
        await asyncio.sleep(self.SHOW_AFTER)
        if gen == self._gen:
            self._set(True, ft.Icons.CLOUD_OFF, "connection lost, reconnecting…", theme.ERROR)

    async def _hide_later(self, gen: int):
        await asyncio.sleep(self.HIDE_AFTER)
        if gen == self._gen:
            self._set(False)

    def _set(self, visible: bool, icon=None, text: str = "", color=None):
        """the connection state to show, visible False: none (the missing services may still keep the strip)"""
        self._connection = (icon, text, color) if visible else None
        self._render()

    def _render(self):
        missing = [] if self._lost else [name for name in Capabilities.missing() if name in SERVICE_ICONS]
        self.missing.controls = [ft.Icon(SERVICE_ICONS[name][0], size=18, color=theme.ON_ACCENT,
                                         tooltip=f"{SERVICE_ICONS[name][1]} unavailable") for name in missing]
        self.missing.visible = bool(missing)
        self.visible = self._connection is not None or bool(missing)
        if self._connection:
            icon, text, color = self._connection
        else:
            icon, text, color = ft.Icons.WARNING_AMBER, "not available:", theme.WARNING
        self.icon.icon = icon
        self.text.value = text
        self.strip.bgcolor = ft.Colors.with_opacity(self.OPACITY, color)
        self.icon.color = self.text.color = theme.ON_ACCENT   # the mode may have changed since start
        try:
            self.update()
        except RuntimeError:
            if self._page:
                self._page.update()  # not mounted as expected, push the whole page instead
