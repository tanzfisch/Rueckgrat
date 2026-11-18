import threading
import time
from datetime import datetime, timezone

from app.common import get_logger, MessageQueue
logger = get_logger()

UPDATE_INTERVAL = 1.0   # seconds: a job's job_update at most this often, a state, step or plan change goes out at once
LINES_INTERVAL = 0.5    # seconds: a watched protocol's new lines go out in a protocol_lines this often
LINES_BATCH = 200       # lines per protocol_lines at most, the rest follow in the next ones
TICK = 0.1              # seconds between the flusher's rounds
IMMEDIATE = ("job_started", "step_started", "plan", "review", "retry", "cancelled", "timed_out", "job_finished", "pass_started", "pass_finished")
WORKER_END = {"done", "timed_out", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def seconds_between(start: str | None, end: str | None = None) -> int | None:
    """whole seconds from start to end (ISO 8601, default now), None without a start"""
    try:
        begin = datetime.fromisoformat(start.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
        return max(0, int((finish - begin).total_seconds()))
    except (AttributeError, ValueError):
        return None


def describe(line: dict) -> str:
    """a line in a few words for the job's last action, e.g. "researcher t2: tool call websearch (failed)" """
    data = line.get("data") or {}
    who = f"{line['agent']} {line['task']}" if line.get("task") else line["agent"]
    what = line["action"].replace("_", " ")
    if line["action"] == "tool_call" and data.get("tool"):
        what += f" {data['tool']}"
    return f"{who}: {what}{' (failed)' if line.get('ok') is False else ''}"


class RunningJob:
    """#215 what the JobMonitor knows of a running agent job or pass: who it is for, its Protocol and its live status
    (state, step / total, the current workers, the last action). changed only by the JobMonitor, with its lock held"""

    def __init__(self, job_id: str, kind: str, name: str, user_id: int, protocol, time_limit: float | None = None,
                 contact_id: int | None = None, conversation_id: int | None = None, source_id: int | None = None, cancel=None):
        self._job_id, self._kind, self._name, self._user_id = job_id, kind, name, user_id
        self._protocol = protocol
        self._time_limit = None if time_limit is None else int(time_limit)
        self._contact_id, self._contact_name = contact_id, None
        self._conversation_id, self._source_id = conversation_id, source_id
        self._cancel = cancel           # callback() that stops the job, None: it can not be cancelled
        self._started_at = utc_now()
        self._finished_at = None
        self._state = "running"
        self._step, self._total, self._percent = 0, 0, 0
        self._current = {}              # the workers of the running step: key (task id or worker id) -> {task, role, state, attempt}
        self._workers = {}              # worker id -> its key in _current
        self._last_action = ""
        self._report_message_id = None

    def job_id(self) -> str:
        return self._job_id

    def user_id(self) -> int:
        return self._user_id

    def contact_id(self):
        return self._contact_id

    def name(self) -> str:
        return self._name

    def protocol(self):
        return self._protocol

    def state(self) -> str:
        return self._state

    def set_contact_name(self, name):
        self._contact_name = name

    def set_report(self, message_id: int):
        self._report_message_id = message_id

    def cancel_callback(self):
        """the cancel callback while the job runs, else None"""
        return self._cancel if self._state == "running" else None

    def set_progress(self, name: str | None, step: int, total: int, percent: int) -> bool:
        """True when the step or total changed (an update at once)"""
        changed = (step, total) != (self._step, self._total)
        self._name = name or self._name
        self._step, self._total, self._percent = step, total, max(0, min(100, int(percent)))
        return changed

    def observe(self, line: dict) -> bool:
        """a new protocol line: the current workers and the last action. True when it changes the state, step or plan"""
        action, data = line["action"], line.get("data") or {}
        if action == "step_started":
            self._current, self._workers = {}, {}
        elif action == "spawned" and data.get("worker_id"):
            key = line.get("task") or data["worker_id"]
            self._current[key] = {"task": line.get("task"), "role": data.get("role"), "state": "running", "attempt": data.get("attempt") or 1}
            self._workers[data["worker_id"]] = key
        elif action in WORKER_END and line["agent_id"] in self._workers:
            entry = self._current.get(self._workers[line["agent_id"]])
            if entry is not None:
                entry["state"] = "done" if line.get("ok") else "failed"
        self._last_action = describe(line)
        return action in IMMEDIATE

    def plan_changed(self, plan: dict | None):
        if plan and plan.get("name"):
            self._name = plan["name"]

    def finish(self, state: str):
        self._state = state
        self._finished_at = utc_now()
        if state == "done":
            self._percent = 100
        for entry in self._current.values():
            if entry["state"] == "running":
                entry["state"] = state

    def payload(self) -> dict:
        """the job_update"""
        return {"job_id": self._job_id, "kind": self._kind, "name": self._name, "state": self._state,
                "contact_id": self._contact_id, "contact_name": self._contact_name, "conversation_id": self._conversation_id,
                "report_message_id": self._report_message_id, "source_id": self._source_id,
                "step": self._step, "total": self._total, "percent": self._percent,
                "current": [dict(entry) for entry in self._current.values()],
                "started_at": self._started_at, "finished_at": self._finished_at,
                "elapsed": seconds_between(self._started_at, self._finished_at), "time_limit": self._time_limit,
                "last_action": self._last_action, "cancellable": self.cancel_callback() is not None,
                "seq": self._protocol.seq() if self._protocol is not None else 0}


class _Watch:
    """one session's view of one protocol: lines up to sent went out, pending ones wait for the flusher. syncing: the
    backlog is being sent, the flusher leaves it alone"""

    def __init__(self, user_id: int, after_seq: int):
        self.user_id = user_id
        self.sent = after_seq
        self.pending = []
        self.plan = None
        self.syncing = True
        self.flushed_at = 0.0


class JobMonitor:
    """#215 the live view of the agent jobs and the companion / task passes for the app's Backroom: who runs, their status
    (job_update to all of the user's websockets, throttled to UPDATE_INTERVAL per job, at once on a state, step or plan
    change), the snapshot (jobs: the running ones and the protocols of the last day), the protocols a session watches
    (protocol_lines, from after_seq on, then live), their long texts (protocol_output) and the cancel. one per hub
    (like MessageQueue). configure() at hub start, until then nothing is pushed"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._lock = threading.Lock()
                instance._jobs = {}             # job_id -> RunningJob
                instance._dirty = set()         # job ids with an update waiting for UPDATE_INTERVAL
                instance._sent_at = {}          # job_id -> monotonic time of its last job_update
                instance._watches = {}          # session -> {job_id: _Watch}
                instance._db = None
                instance._connected = None
                instance._thread = None
                instance._stop = threading.Event()
                cls._instance = instance
            return cls._instance

    def configure(self, db, connected):
        """db: ChatDB (snapshots, backlogs, outputs), connected(user_id): the user has an open websocket. starts the flusher"""
        self._db, self._connected = db, connected
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="job-monitor")
            self._thread.start()

    def stop(self):
        self._stop.set()

    # --- the jobs ---

    def start(self, job: RunningJob):
        """a job or pass starts: registered, its protocol's lines and plans come here"""
        if self._db is not None and job.contact_id() is not None:
            try:
                job.set_contact_name(self._db.contact_name(job.contact_id()))
            except Exception as e:
                logger.warning(f"job {job.job_id()}: no contact name {repr(e)}")
        if job.protocol() is not None:
            job.protocol().set_listener(lambda event, value, job_id=job.job_id(): self._on_event(job_id, event, value))
        with self._lock:
            self._jobs[job.job_id()] = job
            self._send_update(job)

    def progress(self, job_id: str, name: str | None, step: int, total: int, percent: int):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job.set_progress(name, step, total, percent):
                self._send_update(job)
            else:
                self._dirty.add(job_id)

    def finish(self, job_id: str, state: str):
        """the end of a job or pass (done, failed, cancelled): its protocol gets the state, the update goes out at once"""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return
        if job.protocol() is not None:  # stored first: a snapshot from now on finds it finished
            job.protocol().finish(state, job.name())
        with self._lock:
            self._jobs.pop(job_id, None)
            job.finish(state)
            self._dirty.discard(job_id)
            self._sent_at.pop(job_id, None)
            self._send_update(job)

    def report(self, user_id: int, job_id: str, message_id: int):
        """the message that told the user about the job or pass: in its protocol and its update ('open protocol' under it)"""
        if message_id is None:
            return
        try:
            if self._db is not None:
                self._db.set_protocol_report(user_id, job_id, message_id)
        except Exception as e:
            logger.error(f"job {job_id}: report message not stored {repr(e)}")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.set_report(message_id)
                self._send_update(job)
                return
        summary = self._summary(user_id, job_id)
        if summary is not None:
            with self._lock:
                self._broadcast(user_id, {"job_update": summary})

    def cancel(self, user_id: int, job_id: str) -> bool:
        """the user's cancel: stops the user's running job if it can be cancelled. an unknown, finished or foreign job: nothing"""
        with self._lock:
            job = self._jobs.get(job_id)
            callback = job.cancel_callback() if job is not None and job.user_id() == user_id else None
        if callback is None:
            (logger.warning if job else logger.debug)(f"user {user_id}: no cancel of {'foreign or finished' if job else 'unknown'} job {job_id}")
            return False
        try:
            return callback() is not False
        except Exception as e:
            logger.error(f"job {job_id}: cancel failed {repr(e)}")
            return False

    def running(self, user_id: int) -> list:
        """the job ids of the user's running jobs and passes"""
        with self._lock:
            return [job_id for job_id, job in self._jobs.items() if job.user_id() == user_id]

    # --- what the app asks for ---

    def snapshot(self, user_id: int) -> list:
        """the user's running jobs and passes, then the protocols of the last day (all contacts), newest first"""
        with self._lock:
            items = [job.payload() for job in self._jobs.values() if job.user_id() == user_id]
        running = {item["job_id"] for item in items}
        try:
            rows = self._db.protocol_summaries(user_id) if self._db is not None else []
        except Exception as e:
            logger.error(f"user {user_id}: no protocol summaries {repr(e)}")
            rows = []
        items.sort(key=lambda item: item["started_at"], reverse=True)
        return items + [self._row_payload(row) for row in rows if row["job_id"] not in running]

    def send_snapshot(self, user_id: int, session):
        items = self.snapshot(user_id)
        with self._lock:
            self._send(user_id, session, {"jobs": {"items": items}})

    def watch(self, session, user_id: int, job_id: str, after_seq: int = 0) -> bool:
        """the session gets the protocol's lines after after_seq (and its plan), then the new ones as they come. False:
        the user has no protocol with that job_id (protocol_error)"""
        after_seq = max(0, int(after_seq or 0))
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.user_id() != user_id:
                logger.warning(f"user {user_id}: no watch of foreign job {job_id}")
                self._send(user_id, session, {"protocol_error": {"job_id": job_id, "error": "not found"}})
                return False
            watch = _Watch(user_id, after_seq)
            self._watches.setdefault(session, {})[job_id] = watch
            protocol = job.protocol() if job is not None else None
        found = None
        if protocol is None or protocol.store() is not None:
            try:
                found = self._db.protocol_lines(user_id, job_id, after_seq) if self._db is not None else None
            except Exception as e:
                logger.error(f"job {job_id}: no protocol lines {repr(e)}")
        if found is None and protocol is not None:     # not stored: from memory
            found = protocol.plan(), protocol.lines(after_seq)
        with self._lock:
            if self._watches.get(session, {}).get(job_id) is not watch:
                return False    # unwatched or watched again meanwhile
            if found is None:
                self._watches[session].pop(job_id, None)
                self._send(user_id, session, {"protocol_error": {"job_id": job_id, "error": "not found"}})
                return False
            plan, lines = found
            for start in range(0, max(1, len(lines)), LINES_BATCH):
                message = {"job_id": job_id, "lines": lines[start:start + LINES_BATCH]}
                if start == 0:
                    message["plan"] = plan
                self._send(user_id, session, {"protocol_lines": message})
            watch.sent = max(after_seq, lines[-1]["seq"] if lines else 0)
            watch.pending = [line for line in watch.pending if line["seq"] > watch.sent]
            watch.plan, watch.syncing, watch.flushed_at = None, False, time.monotonic()
        return True

    def unwatch(self, session, job_id: str):
        with self._lock:
            self._watches.get(session, {}).pop(job_id, None)

    def disconnect(self, session):
        """the websocket is closed: its watches end"""
        with self._lock:
            self._watches.pop(session, None)

    def send_output(self, session, user_id: int, job_id: str, ref: str):
        """a long text of the user's protocol as protocol_output {job_id, ref, kind, text}, protocol_error if there is none"""
        with self._lock:
            job = self._jobs.get(job_id)
        output = None
        if job is not None and job.user_id() == user_id and job.protocol() is not None and job.protocol().store() is None:
            output = job.protocol().output(ref)
        elif job is None or job.user_id() == user_id:
            try:
                output = self._db.protocol_output(user_id, job_id, ref) if self._db is not None else None
            except Exception as e:
                logger.error(f"job {job_id}: no output {ref} {repr(e)}")
        with self._lock:
            if output is None:
                self._send(user_id, session, {"protocol_error": {"job_id": job_id, "ref": ref, "error": "not found"}})
            else:
                self._send(user_id, session, {"protocol_output": {"job_id": job_id, "ref": ref, "kind": output["kind"], "text": output["text"]}})

    # --- inside ---

    def _summary(self, user_id: int, job_id: str) -> dict | None:
        try:
            row = self._db.protocol_summary(user_id, job_id) if self._db is not None else None
        except Exception as e:
            logger.error(f"job {job_id}: no protocol summary {repr(e)}")
            row = None
        return self._row_payload(row) if row else None

    @staticmethod
    def _row_payload(row: dict) -> dict:
        """the job_update of a stored protocol (finished, or interrupted by a hub restart)"""
        return {"job_id": row["job_id"], "kind": row["kind"], "name": row["name"], "state": row["status"],
                "contact_id": row["contact_id"], "contact_name": row["contact_name"], "conversation_id": row["conversation_id"],
                "report_message_id": row["report_message_id"], "source_id": row["source_id"],
                "step": None, "total": None, "percent": 100 if row["status"] == "done" else None, "current": [],
                "started_at": row["started_at"], "finished_at": row["finished_at"],
                "elapsed": seconds_between(row["started_at"], row["finished_at"]), "time_limit": row["time_limit"],
                "last_action": "", "cancellable": False, "seq": row["seq"]}

    def _on_event(self, job_id: str, event: str, value):
        """a protocol's new line or plan (the Protocol's listener, outside its lock)"""
        with self._lock:
            job = self._jobs.get(job_id)
            immediate = False
            if job is not None:
                if event == "line":
                    immediate = job.observe(value)
                else:
                    job.plan_changed(value)
                    immediate = True
            for watches in self._watches.values():
                watch = watches.get(job_id)
                if watch is None:
                    continue
                if event == "line":
                    if value["seq"] > watch.sent:
                        watch.pending.append(value)
                else:
                    watch.plan = value
            if job is not None:
                if immediate:
                    self._send_update(job)
                else:
                    self._dirty.add(job_id)

    def _send_update(self, job: RunningJob):
        """with the lock held"""
        self._dirty.discard(job.job_id())
        self._sent_at[job.job_id()] = time.monotonic()
        self._broadcast(job.user_id(), {"job_update": job.payload()})

    def _broadcast(self, user_id: int, data: dict):
        """to all of the user's websockets, nothing while none is open (it would pile up in the user's queue). with the
        lock held, so the updates of a job go out in their order"""
        if self._connected is not None and self._connected(user_id):
            MessageQueue().send_data(data, user_id=user_id, session=None)

    def _send(self, user_id: int, session, data: dict):
        if self._connected is not None:
            MessageQueue().send_data(data, user_id=user_id, session=session)

    def flush(self):
        """one round of the flusher: the throttled updates and the watched protocols' new lines that are due"""
        now = time.monotonic()
        with self._lock:
            for job_id in list(self._dirty):
                job = self._jobs.get(job_id)
                if job is None:
                    self._dirty.discard(job_id)
                elif now - self._sent_at.get(job_id, 0.0) >= UPDATE_INTERVAL:
                    self._send_update(job)
            for session, watches in self._watches.items():
                for job_id, watch in watches.items():
                    if watch.syncing or (not watch.pending and watch.plan is None) or now - watch.flushed_at < LINES_INTERVAL:
                        continue
                    lines = [line for line in watch.pending if line["seq"] > watch.sent]
                    batch, watch.pending = lines[:LINES_BATCH], lines[LINES_BATCH:]
                    message = {"job_id": job_id, "lines": batch}
                    if watch.plan is not None:
                        message["plan"], watch.plan = watch.plan, None
                    if batch:
                        watch.sent = batch[-1]["seq"]
                    watch.flushed_at = now
                    self._send(watch.user_id, session, {"protocol_lines": message})

    def _run(self):
        while not self._stop.wait(TICK):
            try:
                self.flush()
            except Exception as e:
                logger.error(f"job monitor flush failed {repr(e)}")
