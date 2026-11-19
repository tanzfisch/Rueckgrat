from datetime import datetime

import flet as ft
from app.ui import theme
from app.utils import Hub

from app.common import get_logger
logger = get_logger()

DIALOG_WIDTH = 560
DIALOG_HEIGHT = 600
DATA_CHARS = 160    # a line's short data on its row, cut after this


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


def local_time(at: str | None) -> str:
    """a line's UTC time (ISO 8601) as local HH:MM:SS"""
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return "??:??:??"


def short_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(f"{v.get('task')} {v.get('role')}" if isinstance(v, dict) else str(v) for v in value) or "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return " ".join(str(value).split())


class ProtocolView(ft.Column):
    """#215 the protocol of an agent job or pass, live: the plan, then a row per line (time, step, task, agent, ok, action,
    its short data). a line's long texts (prompts, results, errors) are fetched when expanded. start() watches it on the
    hub from the last line it has (again after a reconnect), stop() ends that"""

    def __init__(self, job_id: str):
        self._job_id = job_id
        self._seq = 0                       # the last line shown
        self._outputs: dict[str, ft.Text] = {}     # ref -> the text that shows it once fetched
        self._watching = False
        self._plan = ft.Text("", size=12, color=theme.TEXT_DIM, no_wrap=False, visible=False)
        self._status = ft.Text("loading...", size=12, color=theme.TEXT_DIM)
        self._lines = ft.ListView(expand=True, spacing=2, auto_scroll=True)
        super().__init__(controls=[self._plan, self._status, self._lines], expand=True, spacing=6)

    def job_id(self) -> str:
        return self._job_id

    def seq(self) -> int:
        return self._seq

    def start(self):
        if self._watching:
            return
        self._watching = True
        Hub.register_incomming_message(self.on_message)
        Hub.register_connection_state(self.on_connection_state)
        Hub.watch_protocol(self._job_id, self._seq)

    def stop(self):
        if not self._watching:
            return
        self._watching = False
        Hub.unregister_incomming_message(self.on_message)
        Hub.unwatch_protocol(self._job_id)

    def on_connection_state(self, state: str):
        """a new websocket has no watches: again from the last line shown"""
        if state == "reconnected" and self._watching:
            Hub.watch_protocol(self._job_id, self._seq)

    def on_message(self, message: dict):
        try:
            if "protocol_lines" in message and message["protocol_lines"].get("job_id") == self._job_id:
                self._add(message["protocol_lines"])
            elif "protocol_output" in message and message["protocol_output"].get("job_id") == self._job_id:
                output = message["protocol_output"]
                text = self._outputs.get(output.get("ref"))
                if text is not None:
                    text.value = output.get("text") or ""
                    text.italic = False
                    _update(text)
            elif "protocol_error" in message and message["protocol_error"].get("job_id") == self._job_id:
                error = message["protocol_error"]
                text = self._outputs.get(error.get("ref")) if error.get("ref") else None
                if text is not None:
                    text.value = "not found"
                    _update(text)
                else:
                    self._status.value = "this protocol is not there (any more)"
                    _update(self._status)
        except Exception as e:
            logger.error(f"protocol view: message not shown {repr(e)}")

    def _add(self, batch: dict):
        if "plan" in batch:
            self._show_plan(batch.get("plan"))
        new = [line for line in batch.get("lines") or [] if line.get("seq", 0) > self._seq]
        for line in new:
            self._lines.controls.append(self._row(line))
            self._seq = line["seq"]
        self._status.value = f"{self._seq} lines" if self._seq else "no lines yet"
        _update(self._status)
        if new:
            _update(self._lines)

    def _show_plan(self, plan: dict | None):
        if not plan:
            self._plan.visible = False
        else:
            steps = [f"{i}. " + ", ".join(f"{t['task']} {t['role']}" for t in step) for i, step in enumerate(plan.get("steps") or [], 1)]
            self._plan.value = f"plan {plan.get('revision', 0)}: {plan.get('name') or ''}\n" + "\n".join(steps)
            self._plan.visible = True
        _update(self._plan)

    def _row(self, line: dict) -> ft.Control:
        data = dict(line.get("data") or {})
        out = data.pop("out", None) or {}
        where = " ".join(str(part) for part in (line.get("step"), line.get("task")) if part is not None)
        mark = {True: "✓ ", False: "✗ "}.get(line.get("ok"), "")
        summary = "  ".join(f"{key}={short_value(value)}" for key, value in data.items())
        if len(summary) > DATA_CHARS:
            summary = summary[:DATA_CHARS - 1] + "…"
        head = ft.Text(
            spans=[
                ft.TextSpan(f"{local_time(line.get('at'))}  ", ft.TextStyle(color=theme.TEXT_DIM)),
                ft.TextSpan(f"{where + '  ' if where else ''}{line.get('agent')}  "),
                ft.TextSpan(f"{mark}{line.get('action')}", ft.TextStyle(weight=ft.FontWeight.BOLD,
                                                                          color=theme.ERROR if line.get("ok") is False else None)),
                ft.TextSpan(f"  {summary}" if summary else "", ft.TextStyle(color=theme.TEXT_DIM)),
            ],
            size=12, no_wrap=False, selectable=True,
        )
        controls = [head]
        for field, ref in out.items():
            controls.append(self._output(field, ref))
        return ft.Column(controls, spacing=0, tight=True)

    def _output(self, field: str, ref: str) -> ft.Control:
        """a long text: a button, its text is fetched from the hub when it is opened"""
        text = ft.Text("loading...", size=12, italic=True, no_wrap=False, selectable=True, visible=False)
        self._outputs[ref] = text

        def toggle(e):
            text.visible = not text.visible
            if text.visible and text.value == "loading...":
                Hub.get_protocol_output(self._job_id, ref)
            e.control.icon = ft.Icons.EXPAND_LESS if text.visible else ft.Icons.EXPAND_MORE
            _update(e.control)
            _update(text)

        button = ft.TextButton(field, icon=ft.Icons.EXPAND_MORE, on_click=toggle, style=theme.STYLES["button"]["style"])
        return ft.Column([button, ft.Container(text, padding=ft.Padding.only(left=24))], spacing=0, tight=True)


def show_protocol(page: ft.Page, job: dict):
    """the protocol of the job or pass in a dialog, watched while it is open"""
    view = ProtocolView(job["job_id"])

    def close(e=None):
        view.stop()
        page.pop_dialog()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(job.get("name") or "protocol", no_wrap=False),
        content=ft.Container(view, width=DIALOG_WIDTH, height=DIALOG_HEIGHT),
        actions=[ft.TextButton("Close", on_click=close, style=theme.STYLES["button"]["style"])],
        on_dismiss=lambda e: view.stop(),
    )
    page.show_dialog(dialog)
    view.start()
    return view
