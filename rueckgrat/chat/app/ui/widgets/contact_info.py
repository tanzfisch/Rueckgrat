import flet as ft
from app.ui.theme import STYLES, TEXT_DIM
from app.utils import Contact, Hub
from app.common import Utils
from app.ui.widgets.message_box import MessageBox


def _field(label: str, value) -> ft.Control | None:
    if not value:
        return None
    return ft.Column(
        [ft.Text(label, color=TEXT_DIM, size=12), ft.Text(str(value), no_wrap=False, selectable=True)],
        spacing=2,
        tight=True,
    )


class ContactInfo:
    """dialog with what the contact list knows about a contact plus its memories from the hub"""

    @classmethod
    def show(cls, page: ft.Page, contact: Contact):
        profile = Utils.get_nested_value(contact.data, ["profile"], {})
        fields = [
            _field("gender", contact.get_gender()),
            _field("role", contact.get_role()),
            _field("personality", contact.get_persona()),
            _field("background", profile.get("background_hook")),
            _field("relationship", profile.get("relationship")),
            _field("voice", contact.get_voice_id()),
            _field("created", str(contact.data.get("created_at") or "")[:16]),
        ]

        memories = Hub.get_contact_memories(contact.get_id())
        memory_list = ft.ListView(spacing=8, padding=ft.Padding.only(top=8))
        memory_tab = ft.Tab(label=f"Memories ({len(memories or [])})")

        def delete_memory(row: ft.Row, button: ft.IconButton, memory_id: int):
            def delete():
                # the hub can take seconds on mobile data: disable the button until it answers
                button.disabled = True
                button.update()
                if Hub.delete_contact_memory(contact.get_id(), memory_id):
                    memory_list.controls.remove(row)
                    memory_tab.label = f"Memories ({len(memory_list.controls)})"
                    if not memory_list.controls:
                        memory_list.controls.append(ft.Text("Nothing remembered yet", color=TEXT_DIM))
                    memory_tab.update()
                    memory_list.update()
                else:
                    button.disabled = False
                    button.update()
                    MessageBox.error(page, "Could not delete the memory")

            MessageBox.confirm(page, "Are you sure you want to delete this memory?", on_confirm=delete,
                               title="Delete memory", ok_text="Delete")

        def memory_row(m: dict) -> ft.Row:
            button = ft.IconButton(icon=ft.Icons.DELETE, width=40, height=40, style=STYLES["icon_button"]["style"])
            row = ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Text(f"{str(m.get('created_at', ''))[:10]}  {m.get('text', '')}", no_wrap=False, selectable=True, expand=True),
                    button,
                ],
            )
            button.on_click = lambda e: delete_memory(row, button, m["id"])
            return row

        if memories is None:
            memory_list.controls = [ft.Text("Could not load memories", color=TEXT_DIM)]
        elif not memories:
            memory_list.controls = [ft.Text("Nothing remembered yet", color=TEXT_DIM)]
        else:
            memory_list.controls = [memory_row(m) for m in memories]

        # one tab per list, each scrolls on its own: the memories can get long
        content = ft.Tabs(
            length=2,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(tabs=[ft.Tab(label="Contact"), memory_tab]),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            ft.ListView(controls=[f for f in fields if f], spacing=8, padding=ft.Padding.only(top=8)),
                            memory_list,
                        ],
                    ),
                ],
            ),
        )

        page.show_dialog(
            ft.AlertDialog(
                modal=False,
                title=ft.Text(contact.get_name()),
                content=ft.Container(width=400, height=480, content=content),
                actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=STYLES["button"]["style"])],
            )
        )
