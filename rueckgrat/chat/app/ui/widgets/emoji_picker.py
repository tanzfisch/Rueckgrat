import asyncio
import flet as ft


class EmojiPicker(ft.AlertDialog):
    EMOJIS = [
        "😊", "😃", "🤣", "😎", "😍", "😢",
        "😡", "😱", "🤮", "😜", "😴", "😶",
        "😳", "😲", "😈", "😵", "🤔", "🤭",
        "🤫", "🙄", "🥱", "😏", "🫠", "🤦",
        "🤷", "👍", "👎", "✌️", "🤞", "👋",
        "🙏", "🍆", "🍑", "💦", "🔥", "👅",
        "💋", "❤️", "💩", "🥪", "🍿", "💤",
        "📞", "💻", "🔑", "💳", "🎧", "☕",
    ]

    def __init__(self, on_picked=None):
        self.on_picked = on_picked
        self._future = None

        cells = [
            ft.Container(
                content=ft.Text(emoji, size=24, text_align=ft.TextAlign.CENTER),
                alignment=ft.Alignment.CENTER,
                width=40,
                height=40,
                on_click=lambda e, em=emoji: self._pick(em),
            )
            for emoji in self.EMOJIS
        ]

        super().__init__(
            modal=True,
            content=ft.Container(
                content=ft.GridView(
                    controls=cells,
                    runs_count=6,
                    spacing=5,
                    run_spacing=5,
                    padding=5,
                ),
                width=280,
                height=280,
                data={"id": "overlay_dialog"},
            ),
            on_dismiss=self._dismiss,
        )

    def _pick(self, emoji: str):
        if self.on_picked:
            self.on_picked(emoji)
        if self._future and not self._future.done():
            self._future.set_result(emoji)
        if self.page:
            self.page.close(self)

    def _dismiss(self, e):
        if self._future and not self._future.done():
            self._future.set_result("")

    @classmethod
    async def open(cls, page: ft.Page) -> str:
        picker = cls()
        picker._future = asyncio.get_running_loop().create_future()
        page.open(picker)
        return await picker._future