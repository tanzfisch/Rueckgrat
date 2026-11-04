import json
import queue
from typing import Optional, Dict, Any, List, Type, Callable
from uuid import uuid4

from .agent_job import AgentJob, DEFAULT_TIME_LIMIT, RESULTS_MARKER

from app.common import get_logger, Utils
logger = get_logger()

MAX_STEPS = 6               # a plan with more steps is not used (one worker does the whole job)
MAX_WORKERS_PER_STEP = 4    # same for a step with more parallel tasks
MAX_CONTEXT_CHARS = 12000   # the results of the steps before, passed on to the next step and the merge

MAX_NAME_CHARS = 40         # the job's name in the StatusWidget
MAX_REPLANS = 3             # replan / restart of the reviews per job, after that the plan stays (no more reviews)


def short_name(text: str) -> str:
    """the first words of text, at most MAX_NAME_CHARS"""
    name = " ".join(str(text).split()[:5])
    return name if len(name) <= MAX_NAME_CHARS else name[:MAX_NAME_CHARS - 1].rstrip() + "…"

PLAN_PROMPT = """Split a background job into steps for worker agents.

THE JOB:
{prompt}

The steps run one after the other, each step gets the results of the steps before it.
The tasks inside one step run at the same time, so they must not need each other's results.
Use as few steps and tasks as the job needs, at most {max_steps} steps and at most {max_workers} tasks per step. A simple job is one step with one task.
Each task has a role (one or two words, e.g. researcher, analyst, writer) and a prompt: full instructions the worker can follow on its own. Keep every detail of the job the task needs.
Each worker can use the hub's tools on its own, e.g. a web search, reading a web page, wikipedia, the weather, calculations and conversions.
Say in a task's prompt what it has to look up. A research task names the time period (e.g. "2021 to 2031"), the scope
(e.g. country, measure, which kind of predictions) and the sources it must check (e.g. the central bank, the statistics office, the big banks).

Also give the job a short name of two to five words (e.g. "NZ cash rate forecast").

Respond with a json structure like this:
{{
    "name": "...",
    "steps": [
        [{{"role": "researcher", "prompt": "..."}}],
        [{{"role": "analyst", "prompt": "..."}}, {{"role": "analyst", "prompt": "..."}}],
        [{{"role": "writer", "prompt": "..."}}]
    ]
}}
"""

REVIEW_PROMPT = """A background job runs in steps of worker agents. Step {done} of {total} is finished. Decide how the job goes on.

THE JOB:
{prompt}

THE USER'S MESSAGES SINCE THE JOB STARTED (newest last, ignore those that are not about the job):
{messages}

THE RESULTS SO FAR:
{results}

THE REMAINING STEPS:
{remaining}

Choose one action:
- "continue": the remaining steps still fit.
- "replan": the results so far stay, but the remaining steps must change, e.g. a step found nothing useful, the results
  show a better way, or the user added or changed something. Give the new remaining steps.
- "restart": the user changed the job so much that the results so far do not fit any more. Give a new plan from the start.
New steps follow the same rules as the plan: at most {max_steps} steps and at most {max_workers} tasks per step, the tasks
of one step run at the same time, each task has a role and a prompt with full instructions, including the user's changes.

Respond with a json structure like this:
{{
    "action": "continue",
    "name": "only if the job changed: a new short name of two to five words",
    "steps": [
        [{{"role": "researcher", "prompt": "..."}}]
    ]
}}
"steps" only for replan and restart.
"""

MERGE_PROMPT = """Worker agents did a background job step by step. Merge their results into one report.

THE JOB:
{prompt}

THE RESULTS:
{results}

Respond with a json structure like this:
{{
    "summary": "the answer to the job in one or two sentences",
    "details": "what the user needs to know, keep the facts and numbers the workers gave"
}}

Use only what the results say, add nothing.
"""

class Controller(AgentJob):
    """#152 the first agent: the spawn_job tool makes it. it plans the job in steps (one llm call), runs the tasks of
    a step as parallel workers, fails the whole job when a worker fails, passes the results on to the next step and
    merges them at the end. only the Controller spawns: workers are plain AgentJobs without spawn(), and spawn()
    refuses another Controller, so the tree is one level deep"""

    def __init__(self, prompt: str, job_id: Optional[str] = None, time_limit: float = DEFAULT_TIME_LIMIT,
                 infrastructure=None, progress: Optional[Callable[[str, int, int], None]] = None, tool_context: Optional[Dict[str, Any]] = None):
        super().__init__("controller", prompt, job_id, time_limit, infrastructure, tool_context)
        self.progress = progress        # callback(name, step, total): 0, 0 while planning, then the step i of n that starts
        self.name = short_name(prompt)  # the planner's name for the job replaces it
        self.workers: List[AgentJob] = []
        self.plan: Optional[List[List[Dict[str, str]]]] = None   # steps, each a list of parallel tasks {role, prompt}
        self.current: List[AgentJob] = []                        # the workers of the running step
        self.done_steps: List[List[tuple]] = []                  # per finished step: [(role, result)]
        self.inbox: queue.Queue = queue.Queue()                  # the user's messages while the job runs, add_message()
        self.messages: List[str] = []                            # the ones the reviews have read
        self.replans = 0

    def spawn(self, role: str, prompt: str, agent_class: Type[AgentJob] = AgentJob, time_limit: Optional[float] = None) -> AgentJob:
        """makes a worker with a fixed role and starts it on its own thread. without a time limit it gets the controller's"""
        if issubclass(agent_class, Controller):
            raise ValueError("a worker can not be a Controller, only the first agent spawns")
        worker = agent_class(role, prompt, f"{self.job_id[:8]}-{uuid4().hex[:8]}", self.time_limit if time_limit is None else time_limit,
                             infrastructure=self.infrastructure, tool_context=self.tool_context)
        self.workers.append(worker)
        worker.start()
        return worker

    def collect(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """waits for the workers and returns their results, a worker still running gives None"""
        for worker in self.workers:
            worker.join(timeout)
        return [worker.result for worker in self.workers]

    def stop(self):
        """also stops the workers, so a timed out controller ends its workers too"""
        for worker in self.workers:
            worker.stop()
        super().stop()

    def step(self) -> bool:
        """plan, then per step: start its workers, wait for them (briefly per pass, so the loop keeps checking the
        time limit), fail on the first failed worker, go on with the next step. merges after the last step"""
        if self.plan is None:
            self._report_progress(0, 0)
            self.plan = self.make_plan()
        if not self.current:
            self._start_step()
            return False
        finished = [worker for worker in self.current if worker.join(0.05)]
        failed = [worker for worker in finished if not worker.result or "error" in worker.result]
        if failed:
            self.stop()     # the other workers of the step
            raise RuntimeError(f"step {len(self.done_steps) + 1} of {len(self.plan)}: {failed[0].role} failed: {failed[0].result}")
        if len(finished) < len(self.current):
            return False
        self.done_steps.append([(worker.role, worker.result) for worker in self.current])
        self.current = []
        self._review()
        if len(self.done_steps) < len(self.plan):
            return False
        self.result = self._merge()
        return True

    def add_message(self, text: str):
        """a user message for the running job (thread-safe), the review after the current step reads it"""
        self.inbox.put(str(text))

    def _review(self):
        """between steps: one llm call decides with the user's new messages and the results so far whether the remaining
        steps still fit (continue), change and the results stay (replan) or the job starts over (restart).
        no call after the last step when the user said nothing new, none after MAX_REPLANS changes. a bad reply: continue"""
        new = []
        while not self.inbox.empty():
            new.append(self.inbox.get_nowait())
        self.messages += new
        remaining = self.plan[len(self.done_steps):]
        if self.replans >= MAX_REPLANS or not (new or remaining):
            if new:
                logger.info(f"controller {self.job_id}: {len(new)} user message(s) not used, the plan was changed {self.replans} times")
            return
        reply = self.chat([{"role": "user", "content": REVIEW_PROMPT.format(
            prompt=self.prompt, done=len(self.done_steps), total=len(self.plan), results=self._results_text(),
            messages="\n".join(f"- {message}" for message in self.messages) or "none",
            remaining=json.dumps(remaining, ensure_ascii=False) if remaining else "none, the job is merged into a report next",
            max_steps=MAX_STEPS, max_workers=MAX_WORKERS_PER_STEP)}], 0.2)
        data = Utils.json_loads(reply) if reply else None
        action = data.get("action") if isinstance(data, dict) else None
        if isinstance(data, dict) and str(data.get("name") or "").strip():
            self.name = short_name(str(data["name"]).strip())
        steps = self._valid_plan(data) if action in ("replan", "restart") else None
        if steps is None:
            if action != "continue":
                logger.warning(f"controller {self.job_id}: no usable review, the plan stays. reply: {str(reply)[:300]}")
            return
        self.replans += 1
        if action == "restart":
            self.done_steps = []
            self.plan = steps
        else:
            self.plan = self.plan[:len(self.done_steps)] + steps
        logger.info(f"controller {self.job_id}: {action}, plan {[[task['role'] for task in step] for step in self.plan]}")

    def make_plan(self) -> List[List[Dict[str, str]]]:
        """the steps from one llm call. no usable plan: one step, one worker does the whole job"""
        fallback = [[{"role": "worker", "prompt": self.prompt}]]
        reply = self.chat([{"role": "user", "content": PLAN_PROMPT.format(
            prompt=self.prompt, max_steps=MAX_STEPS, max_workers=MAX_WORKERS_PER_STEP)}], 0.2)
        data = Utils.json_loads(reply) if reply else None
        plan = self._valid_plan(data)
        name = str(data.get("name") or "").strip() if isinstance(data, dict) else ""
        if name:
            self.name = short_name(name)
        if plan is None:
            logger.warning(f"controller {self.job_id}: no usable plan, one worker does the whole job. reply: {str(reply)[:300]}")
            return fallback
        logger.info(f"controller {self.job_id}: plan {[[task['role'] for task in step] for step in plan]}")
        return plan

    @staticmethod
    def _valid_plan(plan) -> Optional[List[List[Dict[str, str]]]]:
        """{"steps": [[{role, prompt}, ...], ...]} as a list of steps, None if it is empty, too big or not in that form"""
        steps = plan.get("steps") if isinstance(plan, dict) else None
        if not isinstance(steps, list) or not 0 < len(steps) <= MAX_STEPS:
            return None
        valid = []
        for step in steps:
            step = [step] if isinstance(step, dict) else step     # a step with one task, written without the list
            if not isinstance(step, list) or not 0 < len(step) <= MAX_WORKERS_PER_STEP:
                return None
            tasks = []
            for task in step:
                if not isinstance(task, dict) or not str(task.get("prompt") or "").strip():
                    return None
                tasks.append({"role": str(task.get("role") or "worker").strip()[:40] or "worker", "prompt": str(task["prompt"]).strip()})
            valid.append(tasks)
        return valid

    def _start_step(self):
        if self._stop.is_set():
            return      # cancelled or timed out during a review: no new workers
        index = len(self.done_steps)
        tasks = self.plan[index]
        logger.info(f"controller {self.job_id}: step {index + 1} of {len(self.plan)}: {', '.join(task['role'] for task in tasks)}")
        self._report_progress(index + 1, len(self.plan))
        context = self._results_text()
        for task in tasks:
            prompt = f"{task['prompt']}{RESULTS_MARKER}{context}" if context else task["prompt"]
            self.current.append(self.spawn(task["role"], prompt))

    def _report_progress(self, step: int, total: int):
        if self.progress:
            try:
                self.progress(self.name, step, total)
            except Exception as e:
                logger.warning(f"controller {self.job_id}: progress failed {repr(e)}")

    def _results_text(self) -> str:
        """the results of the finished steps as text, the newest kept if it is too long"""
        parts = []
        for index, step in enumerate(self.done_steps, 1):
            for role, result in step:
                parts.append(f"step {index}, {role}:\n{result.get('summary') or ''}\n{result.get('details') or ''}".strip())
        return "\n\n".join(parts)[-MAX_CONTEXT_CHARS:]

    def _merge(self) -> Dict[str, Any]:
        """one worker: its result as it is. more: one llm call merges them, on a bad reply
        the summaries of the last step and all results as details"""
        results = [result for step in self.done_steps for _, result in step]
        if len(results) == 1:
            return results[0]
        text = self._results_text()
        reply = self.chat([{"role": "user", "content": MERGE_PROMPT.format(prompt=self.prompt, results=text)}], 0.2)
        merged = Utils.json_loads(reply) if reply else None
        if isinstance(merged, dict) and merged.get("summary"):
            return {"summary": str(merged["summary"]), "details": str(merged.get("details") or "")}
        logger.warning(f"controller {self.job_id}: merge failed, results joined. reply: {str(reply)[:300]}")
        return {"summary": " ".join(str(result.get("summary") or "") for _, result in self.done_steps[-1]).strip(), "details": text}
