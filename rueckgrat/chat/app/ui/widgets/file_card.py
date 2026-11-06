"""one card under an assistant message for the files write_file attached. the names shown are the AI's paths"""
import flet as ft
from app.ui import theme
from app.utils import Hub

from app.common import get_logger
logger = get_logger()


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB"


class FileCard(ft.Column):
    def __init__(self, message_id: int, spec: dict):
        super().__init__(spacing=4, tight=True)
        self.message_id = message_id
        self.spec = spec
        members = spec.get("members") or [{
            "real_name": spec.get("file_name") or "file",
            "file_type": spec.get("file_type") or "",
            "file_size": spec.get("file_size") or 0,
            "preview": "",
        }]
        save_name = (spec.get("file_name") or "file").rsplit("/", 1)[-1]
        header = ft.Row([
            ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, color=theme.TEXT),
            ft.Column([
                ft.Text(spec.get("file_name") or save_name, color=theme.TEXT, weight=ft.FontWeight.BOLD,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{_size(spec.get('file_size') or 0)}  {spec.get('file_type') or ''}", size=11, color=theme.TEXT_DIM),
            ], spacing=0, expand=True),
            ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color=theme.TEXT, tooltip=f"Save {save_name}",
                          on_click=lambda e: self.page.run_task(self._save, save_name)),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        tiles = []
        for member in members:
            preview = member.get("preview") or ""
            tiles.append(ft.ExpansionTile(
                title=ft.Text(member["real_name"], size=13, color=theme.TEXT),
                subtitle=ft.Text(_size(member.get("file_size") or 0), size=11, color=theme.TEXT_DIM),
                controls=[ft.Container(
                    content=ft.Text(preview or "(empty)", selectable=True, size=12, color=theme.TEXT,
                                    font_family="monospace", no_wrap=False),
                    padding=8,
                    bgcolor=theme.SURFACE_2,
                    border_radius=theme.RADIUS // 2,
                )],
            ))
        self.controls = [
            ft.Container(content=ft.Column([header, *tiles], spacing=0, tight=True),
                         border=ft.Border.all(1, theme.CODE_BORDER), border_radius=theme.RADIUS // 2, padding=8),
        ]

    async def _save(self, save_name: str):
        data = Hub.get_message_file(self.message_id, self.spec.get("stored_name") or "")
        if data is None or self.page is None:
            return
        picker = ft.FilePicker()
        self.page.overlay.append(picker)
        self.page.update()
        try:
            await picker.save_file(dialog_title="Save file", file_name=save_name, src_bytes=data)
        except Exception as e:
            logger.error(f"saving {save_name} failed: {e}")
        finally:
            self.page.overlay.remove(picker)
            self.page.update()
