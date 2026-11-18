import asyncio

import flet as ft
from app.ui import theme

from app.ui import BasePage
from app.ui.widgets import Header, MessageBox, OneLineBubble, BackroomJobCard, show_protocol
from app.utils import Hub, Backroom
from app.common import get_logger

logger = get_logger()

# the repeats offered (the hub's words, see app/companion/user_tasks.py), a task's other repeat is added when it is edited
REPEATS = ["once", "every 15 minutes", "every 30 minutes", "hourly", "every 2 hours", "every 3 hours", "every 6 hours",
           "every 12 hours", "daily", "weekdays", "weekly"]
EDITOR_WIDTH = 400
WHEN_HINT = "07:30, tomorrow 07:30, friday 18:00, 2026-11-18 07:30 or in 20 minutes"
TICK = 1.0      # seconds: the running jobs' elapsed time


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


class BackroomPage(BasePage):
    """#215 the Backroom: what the contacts do in the background, of all contacts. the agent jobs and the task and
    companion passes (Backroom, live from the hub: running ones and those of the last day) with their protocols and the
    cancel of a running agent job, then #170 the user's scheduled tasks (the task tool, GET /tasks): contact, next run,
    repeat, alarm and text, next first. "+" makes one, a task's buttons show its last run's protocol, change or cancel it"""

    def __init__(self, navigator):
        super().__init__(navigator)
        self._header = Header(navigator, selected_contact=False)
        self._header.on_go_back = self.on_go_back
        self._title = ft.Text("Backroom", size=20, weight=ft.FontWeight.BOLD, color=theme.TEXT)
        self._jobs_status = ft.Text("", color=theme.TEXT_DIM)
        self._jobs_view = ft.Column(spacing=8)
        self._status = ft.Text("loading...", color=theme.TEXT_DIM)
        self._tasks_view = ft.Column(spacing=8)
        self._list_view = ft.ListView(expand=True, spacing=8, controls=[
            self._section("Jobs"), self._jobs_status, self._jobs_view,
            self._section("Scheduled tasks"), self._status, self._tasks_view,
        ])
        self._cards: dict[str, BackroomJobCard] = {}        # job_id -> its card
        self._task_buttons: dict[int, ft.IconButton] = {}   # task id -> its protocol button
        self._contacts: list[dict] = []
        self._ticking = False
        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(expand=True, controls=[self._header, self._title, self._list_view]),
            ),
        ]

    @staticmethod
    def _section(text: str) -> ft.Control:
        return ft.Text(text, weight=ft.FontWeight.BOLD, color=theme.TEXT_LABEL)

    def on_go_back(self, e=None):
        self.navigator.back()

    def on_enter(self, **kwargs):
        Backroom.add_listener(self._on_jobs)
        self.show_jobs()
        self.load_tasks()
        Hub.get_jobs()      # fresh, the listener shows it
        self._ticking = True
        self.page.run_task(self._tick)

    def on_leave(self):
        self._ticking = False
        Backroom.remove_listener(self._on_jobs)

    async def _tick(self):
        while self._ticking:
            await asyncio.sleep(TICK)
            for card in list(self._cards.values()):
                card.tick()

    def _on_jobs(self, job_id):
        """Backroom: a job changed (job_id) or all of them (None)"""
        if job_id is not None and job_id in self._cards and Backroom.job(job_id) is not None:
            card = self._cards[job_id]
            was_running = card.job().get("state") == "running"
            card.set_job(Backroom.job(job_id))
            if was_running == (card.job().get("state") == "running"):
                self._update_task_buttons()
                return      # same place in the list
        self.show_jobs()

    def show_jobs(self):
        jobs = Backroom.jobs()
        cards = {}
        for job in jobs:
            card = self._cards.get(job["job_id"])
            if card is None:
                card = BackroomJobCard(job, on_protocol=self.open_protocol, on_cancel=self.confirm_cancel)
            elif card.job() != job:
                card.set_job(job)
            cards[job["job_id"]] = card
        self._cards = cards
        self._jobs_view.controls = [cards[job["job_id"]] for job in jobs]
        running = Backroom.running_count()
        self._jobs_status.value = (f"{running} running, " if running else "") + f"{len(jobs)} of the last day" if jobs else \
            "nothing running, nothing in the last day"
        self._update_task_buttons()
        _update(self._jobs_status)
        _update(self._jobs_view)

    def _update_task_buttons(self):
        for task_id, button in self._task_buttons.items():
            disabled = Backroom.latest_for_source(task_id) is None
            if button.disabled != disabled:
                button.disabled = disabled
                _update(button)

    def open_protocol(self, job: dict):
        show_protocol(self.page, job)

    def open_task_protocol(self, task: dict):
        """the protocol of the task's last run"""
        job = Backroom.latest_for_source(task["id"])
        if job is not None:
            self.open_protocol(job)

    def confirm_cancel(self, job: dict):
        def cancel():
            if not Hub.cancel_job(job["job_id"]):
                MessageBox.error(self.page, "No connection to the hub, the job runs on.", title="Job not cancelled")

        MessageBox.confirm(self.page, f"Cancel the job \"{job.get('name')}\" of {job.get('contact_name') or 'the contact'}?", cancel,
                           title="Cancel job", ok_text="Cancel job")

    def load_tasks(self):
        tasks, limits = Hub.get_tasks()
        self._contacts = Hub.get_contacts() or []
        add = OneLineBubble("+")
        add.height = 40
        add.on_click = lambda e: self.open_editor(None)
        if tasks is None:
            self._status.value = "the tasks could not be loaded"
            tasks = []
        else:
            limit = f" of {limits['max_tasks']}" if limits.get("max_tasks") else ""
            self._status.value = f"{len(tasks)}{limit} open tasks" if tasks else \
                "no open tasks. ask a contact to remind you of something, or add one here"
        self._task_buttons = {}
        self._tasks_view.controls = [add] + [self._task_card(task) for task in tasks]
        _update(self._status)
        _update(self._tasks_view)

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
                    self._task_protocol_button(task),
                    ft.IconButton(icon=ft.Icons.EDIT, tooltip="change", on_click=lambda e, t=task: self.open_editor(t)),
                    ft.IconButton(icon=ft.Icons.DELETE, tooltip="cancel the task", on_click=lambda e, t=task: self.confirm_delete(t)),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )

    def _task_protocol_button(self, task: dict) -> ft.IconButton:
        button = ft.IconButton(icon=ft.Icons.RECEIPT_LONG, tooltip="protocol of its last run", disabled=Backroom.latest_for_source(task["id"]) is None,
                               on_click=lambda e, t=task: self.open_task_protocol(t))
        self._task_buttons[task["id"]] = button
        return button

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
            value=str(task["contact_id"]) if task else (str(self._contacts[0]["id"]) if len(self._contacts) == 1 else None),
            options=[ft.DropdownOption(key=str(c["id"]), text=c.get("name") or f"#{c['id']}") for c in self._contacts],
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
