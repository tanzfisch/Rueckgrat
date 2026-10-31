import os
import flet as ft

from app.common import get_logger
logger = get_logger()

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"


class StatusWidget(ft.Row):
    def __init__(self, on_cancel_job=None, **kwargs):
        self.on_cancel_job = on_cancel_job      # #152 callback(job_id) of a job row's cancel button, e.g. Hub.cancel_job
        self.gif = ft.Image(src=f"{ASSETS_DIR}/icons/loading.gif", width=20, height=20, visible=False)
        self.label = ft.Text("", visible=False)
        self.jobs = ft.Column(spacing=4, visible=False)     # #152 a row per running background job: name, progress bar
        self.job_rows: dict[str, ft.Row] = {}               # job_id -> its row
        super().__init__(
            controls=[self.gif, self.label, self.jobs, ft.Container(expand=True)],
            spacing=10,
            visible=False,
            **kwargs,
        )

    def _sync(self):
        try:
            self.update()
        except RuntimeError:
            pass

    def clear_status(self):
        self.stop_waiting()
        self.set_text("")
        self.visible = bool(self.job_rows)     # the running jobs stay
        self._sync()

    def on_status_message(self, status: dict):
        if "message" in status:
            self.set_text(status["message"])
            self.start_waiting()
        if status.get("state") == "reset":
            self.clear_status()
            return
        if status.get("state") == "done":
            self.stop_waiting()
            self.label.visible = False
        self._sync()

    def on_job_progress(self, job: dict):
        """#152 MessageQueue.send_job_progress: adds or updates the job's row while it runs, removes it when it is done or failed"""
        job_id = job.get("job_id")
        if not job_id:
            return
        if job.get("state", "running") == "running":
            row = self.job_rows.get(job_id)
            if row is None:
                row = ft.Row([ft.Text("", size=12), ft.ProgressBar(value=0, width=120),
                              ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, tooltip="cancel the job",
                                            on_click=lambda e, job_id=job_id: self._cancel_job(e, job_id))], spacing=8)
                self.job_rows[job_id] = row
                self.jobs.controls.append(row)
            row.controls[0].value = job.get("name") or "background job"
            row.controls[1].value = max(0, min(100, job.get("percent") or 0)) / 100
        elif job_id in self.job_rows:
            self.jobs.controls.remove(self.job_rows.pop(job_id))
        self.jobs.visible = bool(self.job_rows)
        self.visible = self.jobs.visible or self.gif.visible or self.label.visible
        self._sync()

    def _cancel_job(self, e, job_id: str):
        """the hub's job_progress "cancelled" removes the row. not sent (no connection): the button stays"""
        if self.on_cancel_job and self.on_cancel_job(job_id) is not False:
            e.control.disabled = True
            self._sync()

    def set_text(self, text):
        self.label.value = text
        self.label.visible = bool(text)
        self.visible = True

    def start_waiting(self):
        self.gif.visible = True
        self.visible = True

    def stop_waiting(self):
        self.gif.visible = False
