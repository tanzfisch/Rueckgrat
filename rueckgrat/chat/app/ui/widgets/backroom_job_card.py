import flet as ft
from app.ui import theme
from app.utils import Backroom, duration_text

KIND_TEXT = {"job": "agent job", "task": "task", "companion": "companion"}
WORKER_MARKS = {"running": "…", "done": "✓", "failed": "✗", "cancelled": "✗", "timed_out": "✗"}


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


class BackroomJobCard(ft.Container):
    """#215 one agent job, task pass or companion pass in the Backroom: name, contact, kind and state; while it runs its
    step, the current workers, a progress bar, elapsed of its time limit and its last action. buttons: its protocol and
    (an agent job that runs) cancel"""

    def __init__(self, job: dict, on_protocol, on_cancel):
        self._on_protocol = on_protocol     # callback(job)
        self._on_cancel = on_cancel         # callback(job), it asks first
        self._job = job
        self._title = ft.Text("", weight=ft.FontWeight.BOLD, color=theme.TEXT, no_wrap=False)
        self._subtitle = ft.Text("", size=12)
        self._details = ft.Text("", size=12, color=theme.TEXT_DIM, no_wrap=False)
        self._progress = ft.ProgressBar(value=0, color=theme.ACCENT)
        self._timing = ft.Text("", size=12, color=theme.TEXT_DIM, no_wrap=False)
        self._protocol_btn = ft.IconButton(icon=ft.Icons.RECEIPT_LONG, tooltip="open protocol", on_click=lambda e: self._on_protocol(self._job))
        self._cancel_btn = ft.IconButton(icon=ft.Icons.STOP_CIRCLE_OUTLINED, tooltip="cancel the job", on_click=lambda e: self._on_cancel(self._job))
        super().__init__(
            bgcolor=theme.SURFACE_3,
            border_radius=theme.RADIUS,
            padding=ft.Padding.only(left=12, top=8, right=4, bottom=8),
            content=ft.Row(
                [
                    ft.Column([self._title, self._subtitle, self._details, self._progress, self._timing], spacing=2, expand=True),
                    self._protocol_btn,
                    self._cancel_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )
        self._show()

    def job_id(self) -> str:
        return self._job["job_id"]

    def job(self) -> dict:
        return dict(self._job)

    def set_job(self, job: dict):
        self._job = job
        self._show()
        _update(self)

    def tick(self):
        """the elapsed time of a running job goes on"""
        if self._job.get("state") == "running":
            self._timing.value = self._timing_text()
            _update(self._timing)

    def _timing_text(self) -> str:
        job = self._job
        elapsed = Backroom.elapsed(job["job_id"])
        if elapsed is None:
            elapsed = job.get("elapsed")
        text = duration_text(elapsed)
        if job.get("time_limit"):
            text += f" of {duration_text(job['time_limit'])}"
        if job.get("state") == "running" and job.get("last_action"):
            text += f"  ·  {job['last_action']}"
        return text

    def _show(self):
        job = self._job
        running = job.get("state") == "running"
        self._title.value = job.get("name") or "?"
        parts = [job.get("contact_name") or "", KIND_TEXT.get(job.get("kind"), job.get("kind") or ""), job.get("state") or ""]
        self._subtitle.value = "  ·  ".join(part for part in parts if part)
        self._subtitle.color = {"running": theme.ACCENT, "failed": theme.ERROR, "interrupted": theme.ERROR}.get(job.get("state"), theme.TEXT_DIM)
        details = []
        if running and job.get("total"):
            details.append(f"step {job.get('step') or 0} of {job['total']}")
        elif running and job.get("kind") == "job":
            details.append("planning")
        workers = [f"{w.get('role') or '?'}{' ' + w['task'] if w.get('task') else ''} {WORKER_MARKS.get(w.get('state'), '')}".strip()
                   + (f" (attempt {w['attempt']})" if (w.get("attempt") or 1) > 1 else "") for w in job.get("current") or []]
        if running and workers:
            details.append(", ".join(workers))
        self._details.value = "  ·  ".join(details)
        self._details.visible = bool(details)
        self._progress.visible = running
        self._progress.value = (job.get("percent") or 0) / 100 if job.get("total") else None    # None: indeterminate
        self._timing.value = self._timing_text()
        self._cancel_btn.visible = bool(job.get("cancellable"))
