import threading
import time
from datetime import datetime, timezone

SHORT_TEXT = 80     # a text value of a line up to this long stays in the line, a longer one goes to the outputs

# #174 a job's protocol (decision trace), saved by the spawn_job tool when the job ends (ChatDB.save_protocol):
#   lines       one per action, the same fields each: at (UTC), agent (role), agent_id, step (the controller's step,
#               1-based, None outside a step), task (the plan's task id, None for the controller), action, ok (True /
#               False / None), data (the rest). a text longer than SHORT_TEXT is in the outputs: data["out"][key] = ref
#   plan        the current plan only: {"name", "revision", "steps": [[{"task", "role", "prompt" or "out"}]]}. a review
#               that changes it adds a revision, its line says what changed (removed / added task ids). a retry's
#               revised prompt is in its retry line, not in the plan
#   tool_calls  one per tool call: at, agent_id, step, task, tool, args, ok, error, duration_ms. its line has data["call"]
#   outputs     the long texts by ref ("o1", ...): {"kind": the field, "text": in full}
# actions: job_started, plan, step_started, spawned, tools, tool_directing, tool_call, done, failed, timed_out,
#   user_message, cancelled, review (decision keep / refine / restart), retry (a failed task again: attempt, reason,
#   old_prompt, new_prompt, changed), merged, job_finished. a retried task's worker lines have data["attempt"] (2, ...)


class Protocol:
    def __init__(self):
        self._lock = threading.Lock()
        self.lines, self.tool_calls, self.outputs = [], [], {}
        self.plan = None
        self._tasks = 0     # task ids t1, t2, ... are never reused, also not by a new revision

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def _out(self, kind: str, text: str) -> str:
        ref = f"o{len(self.outputs) + 1}"
        self.outputs[ref] = {"kind": kind, "text": text}
        return ref

    def _short(self, data: dict) -> dict:
        """data with its long texts moved to the outputs (with the lock held)"""
        short, out = {}, {}
        for key, value in data.items():
            if isinstance(value, str) and len(value) > SHORT_TEXT:
                out[key] = self._out(key, value)
            elif value is not None:
                short[key] = value
        if out:
            short["out"] = out
        return short

    def add(self, agent: str, agent_id: str, action: str, step=None, task=None, ok=None, **data):
        with self._lock:
            self.lines.append({"at": self.now(), "agent": agent, "agent_id": agent_id, "step": step, "task": task,
                               "action": action, "ok": ok, "data": self._short(data)})

    def tool_call(self, agent: str, agent_id: str, step, task, tool: str, args: str, ok: bool, error, duration_ms: int, attempt=None):
        """one tool call into tool_calls and its line"""
        with self._lock:
            call = len(self.tool_calls) + 1
            self.tool_calls.append({"call": call, "at": self.now(), "agent_id": agent_id, "step": step, "task": task, "tool": tool,
                                    "args": args, "ok": ok, "error": error, "duration_ms": duration_ms})
        self.add(agent, agent_id, "tool_call", step, task, ok, tool=tool, call=call, duration_ms=duration_ms, error=error, attempt=attempt)

    def set_plan(self, name: str, steps: list, keep: int = 0) -> tuple:
        """the plan [[{role, prompt}]] becomes the current one. its first keep steps are the same as before and keep their
        task ids (a refine keeps the done steps), the others get new ids. returns the removed and the added tasks [{task, role}]"""
        with self._lock:
            old = self.plan["steps"] if self.plan else []
            new = [list(step) for step in old[:keep]]
            for step in steps[keep:]:
                tasks = []
                for task in step:
                    self._tasks += 1
                    tasks.append({"task": f"t{self._tasks}", "role": task["role"], **self._short({"prompt": task["prompt"]})})
                new.append(tasks)
            self.plan = {"name": name, "revision": self.plan["revision"] + 1 if self.plan else 0, "steps": new}
            removed = [{"task": t["task"], "role": t["role"]} for step in old[keep:] for t in step]
            added = [{"task": t["task"], "role": t["role"]} for step in new[keep:] for t in step]
            return removed, added

    def task_id(self, step: int, index: int):
        """the id of the plan's task index of step (1-based), None without a plan"""
        with self._lock:
            try:
                return self.plan["steps"][step - 1][index]["task"]
            except (TypeError, IndexError, KeyError):
                return None

    def counts(self, root_id: str) -> dict:
        """agents: spawned by the root (the controller), sub_agents: spawned by those"""
        with self._lock:
            spawned = [line for line in self.lines if line["action"] == "spawned"]
        agents = sum(line["agent_id"] == root_id for line in spawned)
        return {"agents": agents, "sub_agents": len(spawned) - agents}

    def export(self) -> dict:
        """everything for ChatDB.save_protocol"""
        with self._lock:
            return {"plan": self.plan, "lines": list(self.lines), "tool_calls": list(self.tool_calls), "outputs": dict(self.outputs)}


def ms_since(start: float) -> int:
    return round((time.monotonic() - start) * 1000)
