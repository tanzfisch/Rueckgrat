import asyncio
from pathlib import Path
import flet as ft
from app.ui import theme

from app.ui.gallery_page import GalleryPage, broken_image_fallback
from app.ui.widgets.image import Image
from app.utils import Hub, Paths
from app.common import get_logger

logger = get_logger()

IMAGE_SIZE = 120
IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp"]   # what the hub accepts


class ProfileImageView(ft.Container):
    """read-only 120px profile image. Icons.PERSON when none. show() loads from the image cache
    (and starts a download if the file is not there yet). a tap on the photo opens it full screen"""

    def __init__(self, file_key: str | None = None, on_tap=None, **kwargs):
        self.file_key = file_key or ""
        self.on_tap = on_tap
        super().__init__(
            width=IMAGE_SIZE,
            height=IMAGE_SIZE,
            border_radius=8,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.PERSON, size=64),
            on_click=self._on_tap,
            **kwargs,
        )

    def did_mount(self):
        if self.file_key:
            self.show(self.file_key)

    def show(self, file_key: str | None):
        # file names are content hashes, so a cached file is never stale: a new image is a new name
        self.file_key = file_key or ""
        if not self.page:
            return
        if not self.file_key:
            self.content = ft.Icon(ft.Icons.PERSON, size=64)
        else:
            image_path = Paths.get_image_path() / self.file_key
            if not image_path.exists():
                Hub.download_file(f"images/{self.file_key}", Paths.get_image_path())
            image = Image(image_path, size=(IMAGE_SIZE, IMAGE_SIZE), fit=ft.BoxFit.COVER)
            if self.on_tap:
                image.on_tap = self._on_tap     # e.g. the editor opens its dialog instead of the overlay
            self.content = image
            self.page.run_task(broken_image_fallback, self, image_path, lambda: self.content is image)
        self.update()

    def _on_tap(self, e=None):
        if self.on_tap:
            self.on_tap(e)


class ProfileImageSlot(ft.Row):
    """a 120px profile image with an edit button: upload, pick from the gallery, or remove when one is set.
    on_upload(bytes) and on_pick(file_key) return the new file key or None; on_remove() returns True if cleared.
    the hub calls run in a thread. a missing file_key shows Icons.PERSON"""

    def __init__(self, title: str = "Profile image", file_key: str | None = None, on_upload=None, on_pick=None, on_remove=None, visible: bool = True, **kwargs):
        self.title = title
        self.on_upload = on_upload
        self.on_pick = on_pick
        self.on_remove = on_remove
        self.file_picker = ft.FilePicker()
        self.image = ProfileImageView(file_key=file_key, on_tap=self._on_edit_image)

        super().__init__(
            alignment=ft.MainAxisAlignment.CENTER,
            visible=visible,
            controls=[
                ft.Stack(
                    width=IMAGE_SIZE,
                    height=IMAGE_SIZE,
                    controls=[
                        self.image,
                        ft.Container(
                            right=0,
                            bottom=0,
                            border_radius=20,
                            bgcolor=theme.SCRIM_SOFT,
                            content=ft.IconButton(ft.Icons.EDIT, icon_size=18, tooltip="Change image", on_click=self._on_edit_image),
                        ),
                    ],
                ),
            ],
            **kwargs,
        )

    @property
    def file_key(self) -> str:
        return self.image.file_key

    def did_mount(self):
        if self.file_picker not in self.page.services:
            self.page.services.append(self.file_picker)
        if self.file_key:
            self.show(self.file_key)

    def show(self, file_key: str | None):
        self.image.show(file_key)

    def _on_edit_image(self, e=None):
        actions = [
            ft.TextButton("Upload image", on_click=self._on_upload_image, style=theme.STYLES["button"]["style"]),
            ft.TextButton("Choose from gallery", on_click=self._on_choose_from_gallery, style=theme.STYLES["button"]["style"]),
        ]
        if self.file_key and self.on_remove:
            actions.append(ft.TextButton("Remove", on_click=self._on_remove_image, style=theme.STYLES["button"]["style"]))
        actions.append(ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog(), style=theme.STYLES["button"]["style"]))
        self.page.show_dialog(ft.AlertDialog(title=ft.Text(self.title), actions=actions))

    async def _on_upload_image(self, e=None):
        self.page.pop_dialog()
        data = await self._pick_image_bytes()
        if data and self.on_upload:
            await self._apply(self.on_upload, data)

    async def _pick_image_bytes(self) -> bytes | None:
        """android: the phone's photo picker, the bytes come with the result (there may be no file path).
        desktop: a file dialog for the types the hub accepts, the bytes are read from the path"""
        if self.page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
            files = await self.file_picker.pick_files(dialog_title=self.title, file_type=ft.FilePickerFileType.IMAGE, with_data=True)
        else:
            files = await self.file_picker.pick_files(dialog_title=self.title, file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=IMAGE_EXTENSIONS)
        if not files:
            return None
        if files[0].bytes:
            return files[0].bytes
        if files[0].path:
            return Path(files[0].path).read_bytes()
        logger.error("the picked image has neither bytes nor a path")
        return None

    def _on_choose_from_gallery(self, e=None):
        self.page.pop_dialog()

        def close(e=None):
            gallery.on_leave()
            self.page.pop_dialog()

        def select(file_key: str):
            close()
            if self.on_pick:
                self.page.run_task(self._apply, self.on_pick, file_key)

        gallery = GalleryPage(None, on_select=select)
        self.page.show_dialog(
            ft.AlertDialog(
                title=ft.Text("Choose from gallery"),
                content=ft.Container(width=500, height=600, content=gallery),
                actions=[ft.TextButton("Cancel", on_click=close, style=theme.STYLES["button"]["style"])],
                on_dismiss=lambda e: gallery.on_leave(),
            )
        )
        gallery.on_enter()

    async def _on_remove_image(self, e=None):
        self.page.pop_dialog()
        if not self.on_remove:
            return
        ok = await asyncio.to_thread(self.on_remove)
        if not ok:
            self.page.show_dialog(ft.SnackBar(ft.Text("The image could not be removed")))
            return
        self.show("")

    async def _apply(self, send, value):
        """send: an upload (bytes) or pick (file key) call, both answer the new file key"""
        file_key = await asyncio.to_thread(send, value)
        if not file_key:
            self.page.show_dialog(ft.SnackBar(ft.Text("The image could not be set")))
            return
        self.show(file_key)
