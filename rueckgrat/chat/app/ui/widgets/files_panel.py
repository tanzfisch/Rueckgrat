"""the conversation's sandbox files (what bash and run_code wrote, on the hub's docker volume): a folder listing to walk
through, save one file, or save a folder as zip, with or without .git, caches and installed packages.
ChatPage puts it over the conversation on a narrow window and docks it to the right of it on a wide one (dock)"""
import asyncio
import posixpath
import time
import flet as ft
from app.ui import theme
from app.ui.widgets.file_card import size_text
from app.utils import Hub

from app.common import get_logger
logger = get_logger()

ICONS = {"dir": ft.Icons.FOLDER_OUTLINED, "file": ft.Icons.DESCRIPTION_OUTLINED, "link": ft.Icons.LINK}


class FilesPanel(ft.Container):
    WIDTH = 360     # docked on a wide window

    def __init__(self, on_close):
        self.on_close = on_close
        self.conversation_id = None
        self.path = ""              # the folder shown, "" is the root
        self._file_picker = None    # a flet 1.0 service, made on the first save (see FileCard)
        self._load_gen = 0          # only the latest listing is shown
        self.up_btn = ft.IconButton(icon=ft.Icons.ARROW_UPWARD, icon_size=18, icon_color=theme.TEXT, tooltip="Up",
                                    on_click=lambda e: self.open(posixpath.dirname(self.path)))
        self.path_text = ft.Text("/", color=theme.TEXT_DIM, size=12, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                 expand=True)
        self.exclude = ft.Checkbox(label="Skip .git, caches and packages in zips", value=True,
                                   label_style=ft.TextStyle(size=12, color=theme.TEXT_DIM))
        self.status = ft.Text("", size=12, color=theme.TEXT_DIM, visible=False)
        self.listing = ft.ListView(expand=True, spacing=0)
        header = ft.Row([
            ft.Icon(ft.Icons.FOLDER_OPEN, color=theme.TEXT, size=20),
            ft.Text("Files", color=theme.TEXT, weight=ft.FontWeight.BOLD, size=16, expand=True),
            ft.IconButton(icon=ft.Icons.REFRESH, icon_size=20, icon_color=theme.TEXT, tooltip="Refresh",
                          on_click=lambda e: self.refresh()),
            ft.IconButton(icon=ft.Icons.CLOSE, icon_size=20, icon_color=theme.TEXT, tooltip="Close",
                          on_click=lambda e: self.on_close()),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        folder = ft.Row([
            self.up_btn,
            self.path_text,
            ft.IconButton(icon=ft.Icons.FOLDER_ZIP_OUTLINED, icon_size=18, icon_color=theme.TEXT,
                          tooltip="Save this folder as zip", on_click=lambda e: self.page.run_task(self._save_zip, self.path)),
        ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        super().__init__(
            content=ft.Column([header, folder, self.exclude, ft.Divider(height=1, color=theme.CODE_BORDER),
                               self.status, self.listing], expand=True, spacing=4),
            bgcolor=theme.BACKGROUND, padding=ft.Padding(left=12, top=8, right=8, bottom=8),
            top=0, bottom=0, right=0, visible=False,
        )

    def dock(self, wide: bool) -> None:
        """wide: a WIDTH column at the right edge with a line to the conversation, else over all of the conversation"""
        self.left = None if wide else 0
        self.width = self.WIDTH if wide else None
        self.border = ft.Border(left=ft.BorderSide(1, theme.CODE_BORDER)) if wide else None

    def show(self, conversation_id: int) -> None:
        """visible with the root folder of the conversation, the folder shown before when it is the same one"""
        if conversation_id != self.conversation_id:
            self.conversation_id, self.path = conversation_id, ""
        self.visible = True
        self.refresh()

    def open(self, path: str) -> None:
        self.path = path
        self.refresh()

    def refresh(self) -> None:
        if self.page and self.visible and self.conversation_id is not None:
            self.page.run_task(self._load)

    def _set_status(self, text: str) -> None:
        self.status.value = text
        self.status.visible = bool(text)

    async def _load(self):
        self._load_gen += 1
        gen, path = self._load_gen, self.path
        self.up_btn.visible = bool(path)
        self.path_text.value = f"/{path}"
        self._set_status("Loading...")
        self.update()
        entries = await asyncio.to_thread(Hub.get_conversation_files, self.conversation_id, path)
        if gen != self._load_gen or not self.page:
            return
        if entries is None:
            self._set_status("The files could not be loaded.")
            self.listing.controls = []
        else:
            self._set_status("" if entries else
                             "No files yet. What the AI writes with bash or run_code shows up here." if not path else
                             "This folder is empty.")
            self.listing.controls = [self._row(entry) for entry in entries]
        self.update()

    def _row(self, entry: dict) -> ft.Control:
        """a folder opens on a tap and has a zip button, a file has a save button"""
        is_dir = entry["type"] == "dir"
        modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.get("modified") or 0))
        meta = modified if is_dir else f"{size_text(entry.get('size') or 0)}  {modified}"
        if is_dir:
            action = ft.IconButton(icon=ft.Icons.FOLDER_ZIP_OUTLINED, icon_size=18, icon_color=theme.TEXT,
                                   tooltip=f"Save {entry['name']} as zip",
                                   on_click=lambda e, p=entry["path"]: self.page.run_task(self._save_zip, p))
        elif entry["type"] == "file":
            action = ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_size=18, icon_color=theme.TEXT,
                                   tooltip=f"Save {entry['name']}",
                                   on_click=lambda e, p=entry["path"]: self.page.run_task(self._save_file, p))
        else:
            action = ft.Container(width=40)     # a link: the hub serves no links
        return ft.Container(
            content=ft.Row([
                ft.Icon(ICONS.get(entry["type"], ft.Icons.DESCRIPTION_OUTLINED), color=theme.TEXT, size=18),
                ft.Column([
                    ft.Text(entry["name"], color=theme.TEXT, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            weight=ft.FontWeight.BOLD if is_dir else None),
                    ft.Text(meta, color=theme.TEXT_DIM, size=10, max_lines=1),
                ], spacing=0, tight=True, expand=True),
                action,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=4, top=2, right=0, bottom=2),
            border_radius=theme.RADIUS // 2,
            ink=is_dir,
            on_click=(lambda e, p=entry["path"]: self.open(p)) if is_dir else None,
        )

    async def _save_file(self, path: str):
        self._set_status(f"Fetching {posixpath.basename(path)}...")
        self.update()
        data = await asyncio.to_thread(Hub.get_conversation_file, self.conversation_id, path)
        await self._save(posixpath.basename(path), data)

    async def _save_zip(self, path: str):
        name = f"{posixpath.basename(path) or f'conversation_{self.conversation_id}_files'}.zip"
        self._set_status(f"Packing {name}...")
        self.update()
        data = await asyncio.to_thread(Hub.get_conversation_files_zip, self.conversation_id, path, bool(self.exclude.value))
        await self._save(name, data)

    async def _save(self, name: str, data: bytes | None):
        self._set_status("" if data is not None else f"{name} could not be fetched.")
        self.update()
        if data is None:
            return
        if self._file_picker is None:
            self._file_picker = ft.FilePicker()
        try:
            # android needs the bytes, on desktop flet writes them to the chosen path
            await self._file_picker.save_file(dialog_title="Save file", file_name=name, src_bytes=data)
        except Exception as e:
            logger.error(f"saving {name} failed: {e}")
