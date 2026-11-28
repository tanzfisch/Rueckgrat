"""the preview or play button of a file chip (FileCard) and of a file in the files panel: audio opens in AudioPlayer
(and toggles pause if that file is already open), anything else in TextPreview."""
import posixpath
import flet as ft
from app.ui import theme
from .audio_player import AudioPlayer, is_audio
from .text_preview import TextPreview


class FileOpenButton(ft.IconButton):
    def __init__(self, name: str, size: int, fetch, label: str | None = None):
        """name: the path or file name used to detect audio and to identify the open player.
        label: shown in the tooltip, the basename of name if omitted.
        fetch(): the file's bytes or None, run in a thread when it is opened."""
        self._name = name
        self._size = size
        self._fetch = fetch
        self._label = label if label is not None else posixpath.basename(name)
        audio = self.is_audio()
        super().__init__(icon=ft.Icons.PLAY_ARROW if audio else ft.Icons.VISIBILITY_OUTLINED,
                         icon_color=theme.TEXT, icon_size=18,
                         tooltip=f"{'Play' if audio else 'Preview'} {self._label}",
                         on_click=lambda e: self.page.run_task(self.open))

    def is_audio(self) -> bool:
        """AudioPlayer can play this file (the name's or the label's extension)"""
        return is_audio(self._name) or is_audio(self._label)

    def get_name(self) -> str:
        return self._name

    def get_label(self) -> str:
        return self._label

    async def open(self) -> None:
        """plays an audio file (AudioPlayer.play: toggle if this file is already open), else previews it"""
        if self.is_audio():
            await AudioPlayer.play(self.page, self._name, self._size, self._fetch)
        else:
            await TextPreview.open(self.page, self._name, self._size, self._fetch)
