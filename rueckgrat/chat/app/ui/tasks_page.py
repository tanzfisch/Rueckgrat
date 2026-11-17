import flet as ft
from app.ui import theme

from app.ui import BasePage
from app.ui.widgets import Header, MessageBox, OneLineBubble
from app.utils import Hub
from app.common import get_logger

logger = get_logger()

# the repeats offered (the hub's words, see app/companion/user_tasks.py), a task's other repeat is added when it is edited
REPEATS = ["once", "every 15 minutes", "every 30 minutes", "hourly", "every 2 hours", "every 3 hours", "every 6 hours",
           "every 12 hours", "daily", "weekdays", "weekly"]
EDITOR_WIDTH = 400
WHEN_HINT = "07:30, tomorrow 07:30, friday 18:00, 2026-11-18 07:30 or in 20 minutes"


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


class TasksPage(BasePage):
    """#170 the user's open tasks with all contacts (the task tool, GET /tasks): contact, next run, repeat, alarm and text,
    next first. "+" makes one, a task's buttons change or cancel it. the hub checks the values and the limits"""

    def __init__(self, navigator):
        super().__init__(navigator)
        self.header = Header(navigator, selected_contact=False)
        self.header.on_go_back = self.on_go_back
        self.status = ft.Text("loading...", color=theme.TEXT_DIM)
        self.list_view = ft.ListView(expand=True, spacing=8)
        self.contacts: list[dict] = []
        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(expand=True, controls=[self.header, self.status, self.list_view]),
            ),
        ]

    def on_go_back(self, e=None):
        self.navigator.back()

    def on_enter(self, **kwargs):
        self.load_tasks()

    def load_tasks(self):
        tasks, limits = Hub.get_tasks()
        self.contacts = Hub.get_contacts() or []
        add = OneLineBubble("+")
        add.height = 40
        add.on_click = lambda e: self.open_editor(None)
        if tasks is None:
            self.status.value = "the tasks could not be loaded"
            tasks = []
        else:
            limit = f" of {limits['max_tasks']}" if limits.get("max_tasks") else ""
            self.status.value = f"{len(tasks)}{limit} open tasks" if tasks else \
                "no open tasks. ask a contact to remind you of something, or add one here"
        self.list_view.controls = [add] + [self._task_card(task) for task in tasks]
        _update(self.status)
        _update(self.list_view)

    def _task_card(self, task: dict) -> ft.Control:
        details = f"{task['next_run_local']}  ·  {task['repeat_text']}" + ("  ·  ⏰ alarm" if task["alarm"] else "")
        return ft.Container(
            bgcolor=theme.SURFACE_3,
            border_radius=theme.RADIUS,
            padding=ft.Padding.only(left=12, top=8, right=4, bottom=8),
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(task["contact_name"] or "?", weight=ft.FontWeight.BOLD, color=theme.TEXT),
                            ft.Text(details, color=theme.TEXT_DIM, size=12),
                            ft.Text(task["task"], color=theme.TEXT, no_wrap=False),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.IconButton(icon=ft.Icons.EDIT, tooltip="change", on_click=lambda e, t=task: self.open_editor(t)),
                    ft.IconButton(icon=ft.Icons.DELETE, tooltip="cancel the task", on_click=lambda e, t=task: self.confirm_delete(t)),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )

    def confirm_delete(self, task: dict):
        def delete():
            error = Hub.delete_task(task["id"])
            if error:
                MessageBox.error(self.page, error, title="Task not cancelled")
            self.load_tasks()

        MessageBox.confirm(self.page, f"Delete the task \"{task['task']}\" of {task['contact_name']}?", delete,
                           title="Delete task", ok_text="Delete")

    def open_editor(self, task: dict | None):
        """the dialog for a new task (task None) or a change"""
        page = self.page
        repeats = list(REPEATS)
        if task and task["repeat_text"] not in repeats:
            repeats.append(task["repeat_text"])
        contact = ft.Dropdown(
            label="Contact",
            value=str(task["contact_id"]) if task else (str(self.contacts[0]["id"]) if len(self.contacts) == 1 else None),
            options=[ft.DropdownOption(key=str(c["id"]), text=c.get("name") or f"#{c['id']}") for c in self.contacts],
            disabled=task is not None,
            width=EDITOR_WIDTH,
            **theme.STYLES["field"],
        )
        text = ft.TextField(label="Task", value=task["task"] if task else "", multiline=True, min_lines=2, max_lines=5,
                            hint_text="remind me to call mum", **theme.STYLES["field"])
        when = ft.TextField(label="When", value=task["when"] if task else "", hint_text=WHEN_HINT, **theme.STYLES["field"])
        repeat = ft.Dropdown(label="Repeat", value=task["repeat_text"] if task else "once",
                             options=[ft.DropdownOption(key=r, text=r) for r in repeats], width=EDITOR_WIDTH, **theme.STYLES["field"])
        alarm = ft.Switch(label="Alarm (rings the app)", value=bool(task and task["alarm"]), active_color=theme.ACCENT)
        error = ft.Text("", color=theme.ERROR, visible=False, no_wrap=False)

        def save(e):
            if task is None:
                if not contact.value:
                    saved, problem = None, "pick a contact"
                else:
                    saved, problem = Hub.create_task(int(contact.value), text.value or "", when.value or "", repeat.value or "once", bool(alarm.value))
            else:
                changes = {"task": text.value or "", "repeat": repeat.value or "once", "alarm": bool(alarm.value)}
                if (when.value or "") != task["when"]:
                    changes["when"] = when.value or ""
                saved, problem = Hub.edit_task(task["id"], **changes)
            if saved is None:
                error.value, error.visible = problem, True
                _update(error)
                return
            page.pop_dialog()
            self.load_tasks()
            if saved.get("companion_switched_on"):
                MessageBox.show(page, f"Companion mode of {saved['contact_name']} was switched on: tasks only run for companions.",
                                title="Companion on")

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("New task" if task is None else f"Task #{task['id']}"),
            content=ft.Column([contact, text, when, repeat, alarm, error], tight=True, spacing=12, width=EDITOR_WIDTH,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=theme.STYLES["button"]["style"]),
                ft.TextButton("Save", on_click=save, style=theme.STYLES["button"]["style"]),
            ],
        ))
