import asyncio
import flet as ft

from app.ui.theme import STYLES, ERROR
from app.common import get_logger

logger = get_logger()


class MessageBox:
    # builds a plain ft.AlertDialog, the same pattern as the delete contact dialog
    # kind: "question" (ok + cancel), "info", "warning" or "error" (ok only)
    ICONS = {
        "error": (ft.Icons.ERROR_OUTLINE, ERROR),
        "warning": (ft.Icons.WARNING_AMBER, ft.Colors.AMBER),
        "info": (ft.Icons.INFO_OUTLINE, None),
    }

    @classmethod
    def _build(cls, page: ft.Page, message: str, title: str | None, kind: str, on_result=None, ok_text: str = "Ok") -> ft.AlertDialog:
        def close(result: bool):
            page.pop_dialog()
            if on_result:
                on_result(result)

        actions = []
        if kind == "question":
            actions.append(ft.TextButton("Cancel", on_click=lambda e: close(False), style=STYLES["button"]["style"]))
        actions.append(ft.TextButton(ok_text, on_click=lambda e: close(True), style=STYLES["button"]["style"]))

        icon, color = cls.ICONS.get(kind, (None, None))
        if not icon:
            return ft.AlertDialog(
                modal=True,
                title=ft.Text(title) if title else None,
                content=ft.Text(message, text_align=ft.TextAlign.JUSTIFY, no_wrap=False),
                actions=actions,
            )

        # icon on the left, title, message and buttons stacked on the right
        right = []
        if title:
            right.append(ft.Text(title, size=20, weight=ft.FontWeight.BOLD))
        right.append(ft.Text(message, text_align=ft.TextAlign.JUSTIFY, no_wrap=False))
        right.append(ft.Row(actions, alignment=ft.MainAxisAlignment.END))
        return ft.AlertDialog(
            modal=True,
            # flutter's default content padding is 24 at the bottom on top of the button row, keep it tight
            content_padding=ft.Padding.only(left=24, top=24, right=24, bottom=0),
            content=ft.Row(
                [
                    ft.Icon(icon, color=color, size=80),
                    ft.Column(right, tight=True, spacing=12, expand=True),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=16,
                tight=True,
                width=400,
            ),
        )

    @classmethod
    def show(cls, page: ft.Page, message: str, title: str | None = None, kind: str = "info", on_result=None, ok_text: str = "Ok"):
        # fire and forget, usable from sync and async code
        if page is None:
            logger.warning(f"MessageBox: no page, can not show '{title}': {message}")
            return
        page.show_dialog(cls._build(page, message, title, kind, on_result, ok_text))

    @classmethod
    def error(cls, page: ft.Page, message: str, title: str = "Error"):
        logger.error(f"{title}: {message}")
        cls.show(page, message, title, "error")

    @classmethod
    def confirm(cls, page: ft.Page, message: str, on_confirm, title: str | None = None, ok_text: str = "Ok"):
        # yes/no question, calls on_confirm() only when the user presses the ok button
        cls.show(page, message, title, "question", lambda result: on_confirm() if result else None, ok_text)

    @classmethod
    async def open(cls, page: ft.Page, message="Are you sure?", title: str | None = None, kind: str = "question") -> bool:
        # shows the box and waits until it is closed, returns True for ok
        future = asyncio.get_running_loop().create_future()

        def on_result(result: bool):
            if not future.done():
                future.set_result(result)

        cls.show(page, message, title, kind, on_result)
        return await future
