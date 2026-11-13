"""one card under an assistant message for a file write_file attached. the name shown is the AI's path"""
import io
import zipfile
import flet as ft
from app.ui import theme
from app.utils import Hub

from app.common import get_logger
logger = get_logger()


def size_text(n: int) -> str:
    """a byte count to read: 512 B, 3.4 KB, 1.2 MB, 2.0 GB"""
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class FileCard(ft.Container):
    """a chip as wide as its file name needs, at most MAX_WIDTH, the name is cut with ... beyond that"""
    MAX_WIDTH = 400
    CHAR_WIDTH = 8.5    # rough width of one bold name character, only decides when to cap at MAX_WIDTH
    FIXED_WIDTH = 100   # icon, download button, padding and spacing around the name

    def __init__(self, message_id: int, spec: dict):
        self.message_id = message_id
        self.spec = spec
        # FilePicker is a service in flet 1.0, created lazily in the click handler and never put into the overlay
        self._file_picker = None
        file_name = spec.get("file_name") or "file"
        save_name = file_name.rsplit("/", 1)[-1]
        capped = self.FIXED_WIDTH + len(file_name) * self.CHAR_WIDTH > self.MAX_WIDTH
        info = ft.Column([
            ft.Text(file_name, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=13,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(f"{size_text(spec.get('file_size') or 0)}  {spec.get('file_type') or ''}", size=10, color=theme.TEXT_DIM,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=0, tight=True, expand=capped)
        row = ft.Row([
            ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, color=theme.TEXT, size=18),
            info,
            ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color=theme.TEXT, icon_size=18, tooltip=f"Save {save_name}",
                          on_click=lambda e: self.page.run_task(self._save, save_name)),
        ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        # short names keep their natural width, only a long name gets a fixed width so the ellipsis can work
        super().__init__(content=row, width=self.MAX_WIDTH if capped else None,
                         border=ft.Border.all(1, theme.CODE_BORDER), border_radius=theme.RADIUS // 2,
                         padding=ft.Padding(left=10, top=2, right=2, bottom=2))

    async def _save(self, save_name: str):
        data = Hub.get_message_file(self.message_id, self.spec.get("stored_name") or "")
        if data is None:
            return
        if self._file_picker is None:
            self._file_picker = ft.FilePicker()
        try:
            # android needs the bytes, on desktop flet writes them to the chosen path
            await self._file_picker.save_file(dialog_title="Save file", file_name=save_name, src_bytes=data)
        except Exception as e:
            logger.error(f"saving {save_name} failed: {e}")


def _zip_path(file_name: str) -> str:
    """the AI's path as a safe path in the zip: no leading /, no .. or empty parts"""
    parts = [part for part in file_name.replace("\\", "/").split("/") if part not in ("", ".", "..")]
    return "/".join(parts) or "file"


class FileCards(ft.Row):
    """all file chips of one message, side by side and wrapping into the next line once the row is full.
    with two files or more a last chip saves them all as one zip, made fresh in memory on each click (nothing is stored)"""
    def __init__(self, message_id: int):
        super().__init__(wrap=True, spacing=8, run_spacing=8)
        self.message_id = message_id
        self._file_picker = None    # like FileCard: a flet 1.0 service, made on the first click
        self.zip_card = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.FOLDER_ZIP_OUTLINED, color=theme.TEXT, size=18),
                ft.Text("All files", color=theme.TEXT, weight=ft.FontWeight.BOLD, size=13),
                ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color=theme.TEXT, icon_size=18, tooltip="Save all files as zip",
                              on_click=lambda e: self.page.run_task(self._save_zip)),
            ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            border=ft.Border.all(1, theme.CODE_BORDER), border_radius=theme.RADIUS // 2,
            padding=ft.Padding(left=10, top=2, right=2, bottom=2), visible=False,
        )
        self.controls.append(self.zip_card)

    def cards(self) -> list[FileCard]:
        return [control for control in self.controls if isinstance(control, FileCard)]

    def add(self, spec: dict) -> bool:
        """adds the chip of a file (before the zip chip), False if the file is already shown"""
        if any(card.spec.get("stored_name") == spec.get("stored_name") for card in self.cards()):
            return False
        self.controls.insert(self.controls.index(self.zip_card), FileCard(self.message_id, spec))
        self.zip_card.visible = len(self.cards()) > 1
        return True

    def zip_bytes(self) -> bytes | None:
        """the message's files as one zip in memory, each under the AI's path. None if a file could not be fetched"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for card in self.cards():
                data = Hub.get_message_file(self.message_id, card.spec.get("stored_name") or "")
                if data is None:
                    logger.error(f"zip: {card.spec.get('file_name')} could not be fetched")
                    return None
                archive.writestr(_zip_path(card.spec.get("file_name") or "file"), data)
        return buffer.getvalue()

    async def _save_zip(self):
        data = self.zip_bytes()
        if data is None:
            return
        if self._file_picker is None:
            self._file_picker = ft.FilePicker()
        try:
            await self._file_picker.save_file(dialog_title="Save all files", file_name=f"files_{self.message_id}.zip", src_bytes=data)
        except Exception as e:
            logger.error(f"saving the zip of message {self.message_id} failed: {e}")
