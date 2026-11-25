import threading
import time
from datetime import datetime, timezone

from app.common import get_logger
logger = get_logger()

SHORT_TEXT = 80     # a text value of a line up to this long stays in the line, a longer one goes to the outputs


class ProtocolStore:
    """#215 where a Protocol writes as it happens: its row in job_protocols (ChatDB.create_protocol) and the lines, tool
    calls, outputs and plan under it. a failed write is logged, it never fails the job"""

    def __init__(self, db, protocol_id: int):
        self._db = db
        self._id = protocol_id

    @classmethod
    def create(cls, db, job_id: str, kind: str, user_id: int, name: str, **fields):
        """a new protocol row (fields: ChatDB.create_protocol), None if it could not be made (the protocol stays in memory)"""
        try:
            return cls(db, db.create_protocol(job_id, kind, user_id, name, **fields))
        except Exception as e:
            logger.error(f"protocol of {kind} {job_id} not stored {repr(e)}")
            return None

    def protocol_id(self) -> int:
        return self._id

    def _write(self, what: str, call, *args):
        try:
            call(self._id, *args)
        except Exception as e:
            logger.error(f"protocol {self._id}: {what} not stored {repr(e)}")

    def line(self, seq: int, line: dict, outputs: dict):
        self._write("line", self._db.add_protocol_line, seq, line, outputs)

    def tool_call(self, call: dict):
        self._write("tool call", self._db.add_protocol_tool_call, call)

    def plan(self, plan: dict, outputs: dict):
        self._write("plan", self._db.set_protocol_plan, plan, outputs)

    def finish(self, status: str, name: str):
        self._write("finish", self._db.finish_protocol, status, name)


class Protocol:
    """#174 the decision trace of a job (or #215 a companion / task pass): lines (one per action, numbered by seq from 1),
    the workers' tool calls, the long texts (outputs, ref o1, o2, ...) and the current plan. written to its ProtocolStore
    as it happens (none: memory only), the listener gets each new line and plan (JobMonitor, the live view)"""

    def __init__(self, store: ProtocolStore | None = None):
        self._lock = threading.Lock()
        self._store = store
        self._listener = None
        self._lines, self._tool_calls, self._outputs = [], [], {}
        self._plan = None
        self._tasks = 0     # task ids t1, t2, ... are never reused, also not by a new revision

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def set_listener(self, listener):
        """listener(event, value): ("line", the line with its seq) / ("plan", the plan), called outside the lock. None: no listener"""
        self._listener = listener

    def store(self) -> ProtocolStore | None:
        return self._store

    def _notify(self, event: str, value):
        listener = self._listener
        if listener is not None:
            try:
                listener(event, value)
            except Exception as e:
                logger.warning(f"protocol listener failed {repr(e)}")

    def _out(self, kind: str, text: str, new: dict) -> str:
        ref = f"o{len(self._outputs) + 1}"
        self._outputs[ref] = new[ref] = {"kind": kind, "text": text}
        return ref

    def _short(self, data: dict, new: dict) -> dict:
        """data with its long texts moved to the outputs, those also into new (with the lock held)"""
        short, out = {}, {}
        for key, value in data.items():
            if isinstance(value, str) and len(value) > SHORT_TEXT:
                out[key] = self._out(key, value, new)
            elif value is not None:
                short[key] = value
        if out:
            short["out"] = out
        return short

    def add(self, agent: str, agent_id: str, action: str, step=None, task=None, ok=None, **data) -> dict:
        """one line, returns it (with its seq)"""
        with self._lock:
            new = {}
            line = {"seq": len(self._lines) + 1, "at": self.now(), "agent": agent, "agent_id": agent_id, "step": step, "task": task,
                    "action": action, "ok": ok, "data": self._short(data, new)}
            self._lines.append(line)
            if self._store is not None:     # under the lock: the db gets the lines in their order
                self._store.line(line["seq"], line, new)
        self._notify("line", line)
        return line

    def tool_call(self, agent: str, agent_id: str, step, task, tool: str, args: str, ok: bool, error, duration_ms: int, attempt=None):
        """one tool call into the tool calls and its line"""
        with self._lock:
            call = {"call": len(self._tool_calls) + 1, "at": self.now(), "agent_id": agent_id, "step": step, "task": task, "tool": tool,
                    "args": args, "ok": ok, "error": error, "duration_ms": duration_ms}
            self._tool_calls.append(call)
            if self._store is not None:
                self._store.tool_call(call)
        self.add(agent, agent_id, "tool_call", step, task, ok, tool=tool, call=call["call"], duration_ms=duration_ms, error=error, attempt=attempt)

    def set_plan(self, name: str, steps: list, keep: int = 0) -> tuple:
        """the plan [[{role, prompt}]] becomes the current one. its first keep steps are the same as before and keep their
        task ids (a refine keeps the done steps), the others get new ids. returns the removed and the added tasks [{task, role}]"""
        with self._lock:
            new_outputs = {}
            old = self._plan["steps"] if self._plan else []
            new = [list(step) for step in old[:keep]]
            for step in steps[keep:]:
                tasks = []
                for task in step:
                    self._tasks += 1
                    tasks.append({"task": f"t{self._tasks}", "role": task["role"], **self._short({"prompt": task["prompt"]}, new_outputs)})
                new.append(tasks)
            self._plan = {"name": name, "revision": self._plan["revision"] + 1 if self._plan else 0, "steps": new}
            plan = self._copy_plan()
            if self._store is not None:
                self._store.plan(plan, new_outputs)
            removed = [{"task": t["task"], "role": t["role"]} for step in old[keep:] for t in step]
            added = [{"task": t["task"], "role": t["role"]} for step in new[keep:] for t in step]
        self._notify("plan", plan)
        return removed, added

    def finish(self, status: str, name: str):
        """the end of the job: its status (done, failed, cancelled) and name into the store"""
        if self._store is not None:
            self._store.finish(status, name)

    def _copy_plan(self):
        return None if self._plan is None else {**self._plan, "steps": [[dict(task) for task in step] for step in self._plan["steps"]]}

    def plan(self) -> dict | None:
        """a copy of the current plan {name, revision, steps}, None before the first"""
        with self._lock:
            return self._copy_plan()

    def revision(self):
        """the current plan's revision, None before the first"""
        with self._lock:
            return self._plan["revision"] if self._plan else None

    def seq(self) -> int:
        """the seq of the last line, 0 without lines"""
        with self._lock:
            return len(self._lines)

    def lines(self, after_seq: int = 0) -> list:
        """the lines after after_seq"""
        with self._lock:
            return self._lines[max(0, after_seq):]

    def tool_calls(self) -> list:
        with self._lock:
            return list(self._tool_calls)

    def output(self, ref: str) -> dict | None:
        """{kind, text} of a long text, None if there is none with that ref"""
        with self._lock:
            output = self._outputs.get(ref)
            return dict(output) if output else None

    def task_id(self, step: int, index: int):
        """the id of the plan's task index of step (1-based), None without a plan"""
        with self._lock:
            try:
                return self._plan["steps"][step - 1][index]["task"]
            except (TypeError, IndexError, KeyError):
                return None

    def counts(self, root_id: str) -> dict:
        """agents: spawned by the root (the controller), sub_agents: spawned by those"""
        with self._lock:
            spawned = [line for line in self._lines if line["action"] == "spawned"]
        agents = sum(line["agent_id"] == root_id for line in spawned)
        return {"agents": agents, "sub_agents": len(spawned) - agents}

    def export(self) -> dict:
        """everything: plan, lines, tool_calls, outputs"""
        with self._lock:
            return {"plan": self._copy_plan(), "lines": list(self._lines), "tool_calls": list(self._tool_calls), "outputs": dict(self._outputs)}


def ms_since(start: float) -> int:
    return round((time.monotonic() - start) * 1000)
