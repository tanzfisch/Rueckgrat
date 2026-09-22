import asyncio
import flet as ft


class EmojiPicker:
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

    def __init__(self, page: ft.Page):
        self.page = page
        self._future = None
        cells = [
            ft.Container(
                content=ft.Text(emoji, size=24, font_family="Noto Color Emoji", text_align=ft.TextAlign.CENTER),
                alignment=ft.Alignment.CENTER,
                on_click=lambda e, em=emoji: self._pick(em),
            )
            for emoji in self.EMOJIS
        ]
        self.dialog = ft.AlertDialog(
            open=True,
            modal=True,
            content_padding=ft.Padding.all(15),
            actions_padding=ft.Padding.all(0),
            content=ft.Container(
                width=280,
                height=380,
                content=ft.GridView(
                    controls=cells,
                    runs_count=6,
                    max_extent=40,
                    spacing=5,
                    run_spacing=5,
                    padding=5,
                    expand=True,
                ),
            ),
            on_dismiss=self._dismiss,
        )

    def _pick(self, emoji: str):
        if self._future and not self._future.done():
            self._future.set_result(emoji)
        self.page.pop_dialog()

    def _dismiss(self, e):
        if self._future and not self._future.done():
            self._future.set_result("")

    @classmethod
    async def open(cls, page: ft.Page) -> str:
        picker = cls(page)
        picker._future = asyncio.get_running_loop().create_future()
        page.show_dialog(picker.dialog)
        page.update()
        return await picker._future