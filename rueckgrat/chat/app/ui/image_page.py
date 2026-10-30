import asyncio
import os
import uuid
import flet as ft
from app.ui.theme import STYLES

from app.ui import BasePage
from app.ui.widgets import ChatBubble, Header, Image
from app.utils import Hub, Paths
from app.common import get_logger

logger = get_logger()

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"
IMAGE_TIMEOUT = 30    # seconds a stored image may take to arrive in the cache, then the slot shows a warning


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


def _generating(text: str) -> ft.Row:
    """the loading gif of the Image widget (same path and size) and a text"""
    return ft.Row(tight=True, controls=[
        ft.Image(src=f"{ASSETS_DIR}/icons/loading.gif", width=32, height=32, fit=ft.BoxFit.CONTAIN),
        ft.Text(text),
    ])


class ImagePage(BasePage):
    """image generation tool: a prompt in, the generated image below it. tap opens it full screen (save, share).
    the pages are rebuilt on every visit, so the history is not kept here: the hub stores the prompts per user
    (GET /generated-images, also the ones still generating) and the page loads them when it opens. a live result
    fills the entry with the same request id"""

    def __init__(self, navigator):
        super().__init__(navigator)
        self.header = Header(navigator, selected_contact=False)
        self.header.on_go_back = self.on_go_back
        self._active = False
        self._shown: set[str] = set()                 # file names on the page, a result is shown once
        self._requests: set[str] = set()              # request ids on the page (sent, loaded or arrived), an entry is shown once
        self._pending: dict[str, ft.Container] = {}   # request id -> the slot waiting for its image
        self._loading = ft.Container(alignment=ft.Alignment.CENTER, content=_generating("loading..."))
        self.results = ft.ListView(expand=True, spacing=10, padding=0, auto_scroll=True, controls=[self._loading])
        self.prompt_box = ft.TextField(
            hint_text="Describe the image...",
            multiline=True,
            min_lines=1,
            max_lines=4,
            shift_enter=True,   # enter sends, shift+enter is a new line
            on_submit=self.send,
            expand=True,
            border=ft.NoInputBorder(),
        )
        self.send_btn = ft.IconButton(icon=ft.Icons.SEND, icon_size=24, on_click=self.send)
        bar = ft.Container(
            border_radius=20,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            padding=8,
            content=ft.Row(controls=[self.prompt_box, self.send_btn]),
        )
        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(expand=True, controls=[self.header, self.results, bar]),
            ),
        ]

    def on_go_back(self, e=None):
        self.navigator.back()

    def on_enter(self, **kwargs):
        self._active = True
        Hub.register_incomming_message(self.on_incomming_message)
        self.page.run_task(self._load_history)

    def on_leave(self):
        self._active = False
        Hub.unregister_incomming_message(self.on_incomming_message)

    async def _load_history(self):
        images = await asyncio.to_thread(Hub.get_generated_images)
        if not self._active or self._loading not in self.results.controls:
            return
        if images is None:
            self._loading.content = ft.Text("⚠ could not load earlier images", color=ft.Colors.ERROR)
            _update(self._loading)
            return
        try:
            rows = self._history_rows(images)
        except Exception as e:      # e.g. rows in a shape this page does not know: a warning, never the loader forever
            logger.error(f"failed to show generated images {repr(e)}")
            self._loading.content = ft.Text("⚠ could not show earlier images", color=ft.Colors.ERROR)
            _update(self._loading)
            return
        # the history goes where the loading text was, in front of what was sent or arrived meanwhile
        index = self.results.controls.index(self._loading)
        self.results.controls[index:index + 1] = rows
        _update(self.results)

    def _history_rows(self, images: list[dict]) -> list[ft.Control]:
        rows = []
        for item in images:
            # rows of a hub that still runs the first version have no request_id and no status: they are done images
            request_id, status = item.get("request_id"), item.get("status", "done")
            # an entry that was sent or arrived while loading is already there
            if item.get("file_name") in self._shown or (request_id and request_id in self._requests):
                continue
            if request_id:
                self._requests.add(request_id)
            if status == "done":
                self._shown.add(item["file_name"])
                slot = self._image_slot(item["file_name"])
            elif status == "pending":
                slot = self._pending_slot(request_id)    # the live result fills it
            else:
                slot = self._error_slot("image generation failed or was interrupted")
            rows += self._rows(item["prompt"], slot)
        return rows

    @staticmethod
    def _rows(prompt: str, slot: ft.Container) -> list[ft.Control]:
        prompt_row = ft.Row(controls=[ft.Container(expand=15), ft.Container(content=ChatBubble("user", prompt), expand=85, **STYLES["chat_user"])])
        return [prompt_row, slot]

    def _image_slot(self, filename: str) -> ft.Container:
        slot = ft.Container(alignment=ft.Alignment.CENTER)
        self._show_image(slot, filename)
        return slot

    def _show_image(self, slot: ft.Container, filename: str):
        # same as chat images: download into the image cache, Image shows it once the file is there
        image_path = Paths.get_image_path() / filename
        if not image_path.exists():
            Hub.download_file(f"images/{filename}", Paths.get_image_path())
        slot.content = Image(image_path)
        self.page.run_task(self._give_up, slot, image_path)

    async def _give_up(self, slot: ft.Container, image_path):
        """the Image widget waits for the file forever. the hub has it already, so if the download failed
        (401 after the token ran out, 404, hub down) it will not come: warn instead of an endless loader"""
        await asyncio.sleep(IMAGE_TIMEOUT)
        if not image_path.exists():
            slot.content = self._error_slot("image could not be loaded").content
            _update(slot)

    def _pending_slot(self, request_id: str) -> ft.Container:
        slot = ft.Container(alignment=ft.Alignment.CENTER, content=_generating("generating..."))
        self._pending[request_id] = slot
        return slot

    @staticmethod
    def _error_slot(error: str) -> ft.Container:
        return ft.Container(alignment=ft.Alignment.CENTER, content=ft.Text(f"⚠ {error}", color=ft.Colors.ERROR))

    def _add(self, rows: list[ft.Control]):
        self.results.controls += rows
        _update(self.results)

    def send(self, e=None):
        prompt = (self.prompt_box.value or "").strip()
        if not prompt:
            return
        request_id = uuid.uuid4().hex
        if not Hub.generate_image(prompt, request_id):
            return  # not connected, the connection banner shows it
        self.prompt_box.value = ""
        _update(self.prompt_box)
        self._requests.add(request_id)
        self._add(self._rows(prompt, self._pending_slot(request_id)))

    def on_incomming_message(self, message: dict):
        if "generated_image" not in message:
            return
        generated = message["generated_image"]
        filename = generated.get("filename")
        if filename and filename in self._shown:
            return
        slot = self._pending.pop(generated.get("request_id"), None)
        self._requests.add(generated.get("request_id"))
        # a result nobody on this page asked for (earlier visit of this page, another device): the hub stored it, show it here too
        new_slot = ft.Container(alignment=ft.Alignment.CENTER) if slot is None else None
        if new_slot is not None:
            slot = new_slot
        if filename:
            self._shown.add(filename)
            self._show_image(slot, filename)
        else:
            slot.content = self._error_slot(generated.get("error", "image generation failed")).content
        if new_slot is not None:
            self._add(self._rows(generated.get("prompt", ""), new_slot))
        else:
            _update(slot)
