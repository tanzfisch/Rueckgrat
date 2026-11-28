"""a simple player for an audio file of the files panel, shown over the page like TextPreview: play / pause, 15 s back
and forward, a slider to jump anywhere with the time and the length. not a full player, the user has better apps for
that. the bytes are fetched on each open and only kept by the player; a Playback plays them (flet's Audio service on
mobile and web, soundfile + sounddevice on desktop, see audio_playback). closing it stops the playback and releases it"""
import asyncio
import posixpath
import flet as ft
from app.ui import theme
from .message_box import MessageBox
from .audio_playback import Playback

from app.common import get_logger
logger = get_logger()

AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".opus", ".oga", ".m4a", ".aac", ".flac")
SKIP_MS = 15000             # a jump back or forward
MAX_SIZE = 50 * 1024 * 1024  # bigger files are only played after the user agreed (all of it goes to the player at once)
CARD_WIDTH = 420


def is_audio(name: str) -> bool:
    """an audio file by its name, the player can play it"""
    return posixpath.splitext(name.lower())[1] in AUDIO_EXTENSIONS


def time_text(ms: int) -> str:
    """m:ss, h:mm:ss from an hour on"""
    seconds = max(0, int(ms // 1000))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


class AudioPlayer(ft.Container):
    def __init__(self, page: ft.Page, name: str, data: bytes):
        self._page = page           # given by open(): self.page only exists while mounted, the player needs it before
        self._mounted = False       # shown on the page (did_mount .. will_unmount): only then it is updated
        self._name = name
        self._data = data
        self._playback = None       # Playback, made when it is shown (start), None once released
        self._duration_ms = 0
        self._position_ms = 0
        self._playing = False
        self._started = False       # play() once, resume() after a pause
        self._loaded = False        # the playback has loaded: before, the controls do nothing (it plays by itself then)
        self._dragging = False      # the slider is held: positions don't move it
        self._play_btn = ft.IconButton(icon=ft.Icons.PLAY_ARROW, icon_size=36, icon_color=theme.TEXT, tooltip="play",
                                       on_click=lambda e: self._page.run_task(self.toggle))
        self._slider = ft.Slider(min=0, max=1, value=0, expand=True, on_change_start=self._drag_start,
                                 on_change_end=lambda e: self._page.run_task(self.seek, int(float(e.control.value) * 1000)))
        self._time = ft.Text(self._times(), color=theme.TEXT_DIM, size=12)
        card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.AUDIOTRACK, color=theme.TEXT, size=18),
                    ft.Text(posixpath.basename(name), color=theme.TEXT, weight=ft.FontWeight.BOLD, size=14, expand=True,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.IconButton(icon=ft.Icons.CLOSE, icon_size=20, icon_color=theme.TEXT, tooltip="Close",
                                  on_click=self._close),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([self._slider], spacing=0),
                ft.Row([self._time], alignment=ft.MainAxisAlignment.END),
                ft.Row([
                    ft.IconButton(icon=ft.Icons.FAST_REWIND, icon_size=28, icon_color=theme.TEXT, tooltip="back 15 s",
                                  on_click=lambda e: self._page.run_task(self.skip, -SKIP_MS)),
                    self._play_btn,
                    ft.IconButton(icon=ft.Icons.FAST_FORWARD, icon_size=28, icon_color=theme.TEXT, tooltip="forward 15 s",
                                  on_click=lambda e: self._page.run_task(self.skip, SKIP_MS)),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=12),
            ], spacing=4, tight=True),
            width=CARD_WIDTH,
            bgcolor=theme.BACKGROUND, border_radius=theme.RADIUS, border=ft.Border.all(1, theme.CODE_BORDER),
            padding=ft.Padding(left=12, top=4, right=4, bottom=12),
            on_click=lambda e: None,    # a tap on the player does not close it, only one beside it
        )
        # page.overlay gets no safe area from the view (see ImageOverlay)
        super().__init__(left=0, top=0, right=0, bottom=0, bgcolor=theme.SCRIM, on_click=self._close, padding=16,
                         alignment=ft.Alignment.CENTER, content=ft.SafeArea(content=card))

    @property
    def duration_ms(self) -> int:
        return self._duration_ms

    @property
    def position_ms(self) -> int:
        return self._position_ms

    @property
    def playing(self) -> bool:
        return self._playing

    def clamp(self, ms: float) -> int:
        """a position inside the track: 0 .. its length (0 while the length is not known)"""
        return int(max(0, min(ms, self._duration_ms)))

    def _times(self) -> str:
        return f"{time_text(self._position_ms)} / {time_text(self._duration_ms)}"

    def _make_playback(self) -> Playback:
        return Playback.make(self._page, self._data, on_duration=self._on_duration, on_position=self._on_position,
                             on_completed=self._on_completed, on_paused=self._on_paused, on_failed=self._on_failed)

    def start(self) -> None:
        """shown: the playback is made, loaded and played from the start"""
        self._playback = self._make_playback()
        self._page.run_task(self._autoplay, self._playback)

    async def _autoplay(self, playback: Playback) -> None:
        """plays once loaded, unless loading failed (on_failed dropped it) or it was closed meanwhile"""
        await playback.load()
        if self._playback is playback:
            self._loaded = True
            await self.toggle()

    async def toggle(self) -> None:
        """play from where it is, or pause"""
        playback = self._playback
        if playback is None or not self._loaded:
            return
        if self._playing:
            await playback.pause()
        elif self._started:
            await playback.resume()
        else:
            self._started = True
            await playback.play(self._position_ms)
        if self._playback is playback:  # not closed or failed meanwhile
            self._set_playing(not self._playing)

    async def skip(self, delta_ms: int) -> None:
        await self.seek(self._position_ms + delta_ms)

    async def seek(self, ms: float) -> None:
        """jumps to ms, kept inside the track"""
        self._dragging = False
        self._position_ms = self.clamp(ms)
        self._show_position()
        if self._playback is not None and self._started:
            await self._playback.seek(self._position_ms)

    def _drag_start(self, e) -> None:
        self._dragging = True

    def _set_playing(self, playing: bool) -> None:
        self._playing = playing
        self._play_btn.icon = ft.Icons.PAUSE if playing else ft.Icons.PLAY_ARROW
        self._play_btn.tooltip = "pause" if playing else "play"
        self._refresh()

    def _show_position(self) -> None:
        if not self._dragging:
            self._slider.value = self._position_ms / 1000
        self._time.value = self._times()
        self._refresh()

    def _on_duration(self, ms: int) -> None:
        self._duration_ms = int(ms)
        self._slider.max = max(1, self._duration_ms / 1000)
        self._position_ms = self.clamp(self._position_ms)
        self._show_position()

    def _on_position(self, ms: int) -> None:
        self._position_ms = self.clamp(ms)
        self._show_position()

    def _on_completed(self) -> None:
        self._started = False       # the next play starts at the beginning
        self._position_ms = 0
        self._show_position()
        self._set_playing(False)

    def _on_paused(self) -> None:
        self._set_playing(False)

    def _on_failed(self, text: str) -> None:
        """the file can't be played here: said in the player, the controls do nothing"""
        logger.error(f"playing {self._name} failed: {text}")
        playback, self._playback = self._playback, None
        if playback is not None:
            self._page.run_task(playback.release)
        self._time.value = "can't play this file"
        self._set_playing(False)

    def did_mount(self):
        super().did_mount()
        self._mounted = True

    def will_unmount(self):
        """off the page however it went: the playback stops too (stop does nothing a second time)"""
        self._mounted = False
        if self._playback is not None:
            self._page.run_task(self.stop)
        super().will_unmount()

    def _refresh(self) -> None:
        """redrawn while it is shown; before it is mounted or after it closed the values are only kept"""
        if self._mounted:
            self.update()

    async def stop(self) -> None:
        """the playback stops and is released, for good"""
        playback, self._playback = self._playback, None
        self._playing = False
        if playback is None:
            return
        try:
            await playback.release()
        except Exception as e:
            logger.error(f"releasing the audio of {self._name} failed: {e}")

    def _close(self, e=None):
        page = self._page
        if self in page.overlay:
            self._mounted = False   # nothing redraws it from here on, a late position report included
            page.run_task(self.stop)
            page.overlay.remove(self)
            page.update()

    def get_name(self) -> str:
        """the file this player was opened for (the path or name given to open)"""
        return self._name

    @classmethod
    def current(cls, page: ft.Page):
        """the player shown on the page, None if none is open"""
        for control in reversed(page.overlay):
            if isinstance(control, cls):
                return control
        return None

    @classmethod
    def close_open(cls, page: ft.Page) -> bool:
        """closes the player if one is shown (and stops it), returns True if it did"""
        player = cls.current(page)
        if player is None:
            return False
        player._close()
        return True

    @classmethod
    async def play(cls, page: ft.Page, name: str, size: int, fetch) -> None:
        """opens and plays the file (open), or toggles pause if this file is already in the open player"""
        player = cls.current(page)
        if player is not None and player.get_name() == name:
            await player.toggle()
            return
        await cls.open(page, name, size, fetch)

    @classmethod
    async def open(cls, page: ft.Page, name: str, size: int, fetch) -> None:
        """fetch(): the file's bytes or None, run in a thread. a file over MAX_SIZE asks first"""
        if size > MAX_SIZE and not await MessageBox.open(
                page, f"{posixpath.basename(name)} is {size / 1024 / 1024:.1f} MB. Loading it can take a while. Play it anyway?",
                "Big file", "question"):
            return
        data = await asyncio.to_thread(fetch)
        if data is None:
            MessageBox.error(page, f"{posixpath.basename(name)} could not be fetched.")
            return
        cls.close_open(page)    # one player at a time
        player = cls(page, name, data)
        page.overlay.append(player)
        page.update()       # mounted, then the playback is made and loaded
        player.start()
