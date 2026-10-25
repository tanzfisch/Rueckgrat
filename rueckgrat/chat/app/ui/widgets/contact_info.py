import flet as ft
from app.ui.theme import STYLES, TEXT_DIM
from app.utils import Contact, Hub
from app.common import Utils


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
        if memories is None:
            memory_controls = [ft.Text("Could not load memories", color=TEXT_DIM)]
        elif not memories:
            memory_controls = [ft.Text("Nothing remembered yet", color=TEXT_DIM)]
        else:
            memory_controls = [
                ft.Text(f"{str(m.get('created_at', ''))[:10]}  {m.get('text', '')}", no_wrap=False, selectable=True)
                for m in memories
            ]

        # one tab per list, each scrolls on its own: the memories can get long
        content = ft.Tabs(
            length=2,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(tabs=[ft.Tab(label="Contact"), ft.Tab(label=f"Memories ({len(memories or [])})")]),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            ft.ListView(controls=[f for f in fields if f], spacing=8, padding=ft.Padding.only(top=8)),
                            ft.ListView(controls=memory_controls, spacing=8, padding=ft.Padding.only(top=8)),
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
