import json
import posixpath
import queue
import re
from typing import Optional, Dict, Any, List, Type, Callable, Tuple
from uuid import uuid4

from .agent_job import AgentJob, DEFAULT_TIME_LIMIT
from .worker import Worker, TIME_LIMIT as WORKER_TIME_LIMIT
from .check import Check, NAMED_FILE
from . import prompts
from .protocol import Protocol
from app.tools.bash_tool import BashTool     # the projects listed as its prompt lists them
from app.utils.sandbox_volume import SandboxVolume, MOUNT_PATH, PROJECTS

from app.common import get_logger
logger = get_logger()

MAX_STEPS = 6               # a plan with more steps is not used (one worker does the whole job)
MAX_CONTEXT_CHARS = 12000   # the results of the steps before, passed on to the next step and into the job's result
MAX_DELIVERED = 20          # folder files one job gives the user (delivery)
# build output a job never delivers (delivery)
BUILT = re.compile(r"(?:^|/)(?:build|cmake-build-[^/]*|CMakeFiles|dist|target)/|\.(?:o|obj|a|so|pyc|class|exe)$")

MAX_NAME_CHARS = 40         # the job's name in the StatusWidget
MAX_TASK_RETRIES = 1        # a task whose check failed runs again this often, told what failed, before the job fails
# a task that makes or uses files or runs something: it names a path in the contact's files or a file by its name
# (main.py, css/style.css, `app.js`). a plain ".js" only with a folder or in backticks, "Node.js" is a name too
FILE_TASK = re.compile(r"~/|/home/|`[^`\s]+\.js`|(?<![\w.])[\w-]+/[\w./-]*\.js\b|(?<![\w.])[\w-]+(?:/[\w.-]+)*\.(?:py|ipynb|ts|tsx|jsx|"
                       r"html?|css|scss|md|txt|json|ya?ml|toml|ini|cfg|sh|csv|tsv|xml|svg|png|jpe?g|gif|webp|bmp|mp3|ogg|wav|"
                       r"c|cc|cpp|h|hpp|rs|go|java|kt|rb|php|lua|sql|pdf|docx?|xlsx?)\b", re.IGNORECASE)
LINK = re.compile(r"\b(?:https?|ftp)://\S+|\bwww\.\S+", re.IGNORECASE)    # a link names a page, not a file to make (file_task)
NAMED_PROJECT = re.compile(rf"(?:~|{re.escape(MOUNT_PATH)})/{re.escape(PROJECTS)}/([\w.-]+)")    # a project folder a text names


def file_task(text: str) -> bool:
    """text (a task or a job) makes or uses files or runs commands: FILE_TASK outside its links"""
    return bool(FILE_TASK.search(LINK.sub(" ", text or "")))


def short_name(text: str) -> str:
    """the first words of text, at most MAX_NAME_CHARS"""
    name = " ".join(str(text).split()[:5])
    return name if len(name) <= MAX_NAME_CHARS else name[:MAX_NAME_CHARS - 1].rstrip() + "…"

class Controller(AgentJob):
    """#152 the first agent: the spawn_job tool makes it. #230 the job's folder and its steps, each a goal with its check,
    are decided once at the start (make_plan, one llm call). each step is one worker (Worker: a loop until it says done
    or its calls or time run out), then only the step's check decides (Check): passed -> the next step, after the last
    the result with the files (delivery); failed -> one retry told what failed, then the job fails. the user's messages
    while it runs go into the next worker's goal. only the Controller spawns, and spawn() refuses another Controller,
    so the tree is one level deep"""

    def __init__(self, prompt: str, job_id: Optional[str] = None, time_limit: float = DEFAULT_TIME_LIMIT,
                 infrastructure=None, progress: Optional[Callable[[str, int, int], None]] = None, tool_context: Optional[Dict[str, Any]] = None,
                 protocol: Optional[Protocol] = None):
        super().__init__("controller", prompt, job_id, time_limit, infrastructure, tool_context)
        self.progress = progress        # callback(name, step, total): 0, 0 while planning, then the step i of n that starts
        self.name = short_name(prompt)  # the planner's name for the job replaces it
        self.workers: List[Worker] = []     # every worker it started, the retried ones too
        self.plan: Optional[List[Dict[str, str]]] = None    # the steps {role, prompt (the goal), check}
        self.current: Optional[Worker] = None   # the running step's worker
        self.done: List[Worker] = []            # the workers whose check passed, one per finished step
        self._inbox: queue.Queue = queue.Queue()    # the user's messages while the job runs (add_message)
        self._messages: List[str] = []              # the ones read so far, every worker after them gets them
        self._folder = ""           # the job's folder below MOUNT_PATH (projects/<name> or the workdir, _choose_folder), "" without tools
        self._renaming = None       # (the folder the plan named, the one the job got) when they differ (_choose_folder, _renamed)
        self.protocol = protocol or Protocol()  # #174 the job's decision trace, its workers write into it too. #215 the spawn tool's is stored as it happens
        self.trace("job_started", prompt=prompt)

    def spawn(self, role: str, prompt: str, check: str = "", agent_class: Type[Worker] = Worker, time_limit: Optional[float] = None,
              step: Optional[int] = None, task: Optional[str] = None, attempt: int = 1) -> Worker:
        """makes a worker with a fixed role, its goal (prompt) and its check (Check: the plan's command or the default of
        its goal) and starts it on its own thread. without a time limit it gets a worker's (WORKER_TIME_LIMIT), at most
        the controller's"""
        if issubclass(agent_class, Controller):
            raise ValueError("a worker can not be a Controller, only the first agent spawns")
        worker = agent_class(role, prompt, f"{self.job_id[:8]}-{uuid4().hex[:8]}",
                             min(self.time_limit, WORKER_TIME_LIMIT) if time_limit is None else time_limit,
                             infrastructure=self.infrastructure, tool_context=self.tool_context)
        self.workers.append(worker)
        worker.protocol, worker.plan_step, worker.plan_task, worker.attempt = self.protocol, step, task, attempt
        worker.set_folder(self._folder)
        goal = prompt.partition(prompts.RESULTS_MARKER_PART)[0]
        planned = Check(check, goal, worker.folder())
        worker.check = planned.command()
        self.trace("spawned", step=step, task=task, worker_id=worker.job_id, role=role, attempt=attempt if attempt > 1 else None,
                   prompt=goal, check=worker.check or None, **({"check_replaced": check} if planned.replaced() else {}))
        worker.start()
        return worker

    def stop(self):
        """also stops the workers, so a timed out controller ends its workers too"""
        for worker in self.workers:
            worker.stop()
        super().stop()

    def step(self) -> bool:
        """plan, then per step one worker: start it, wait for it (briefly per pass, so the loop keeps checking the time
        limit), then its check (_check): passed -> the next step, after the last the result (the last summary, every
        step's result with its check) with the files (delivery);
        failed -> one retry told what failed (MAX_TASK_RETRIES), then the job fails"""
        if self.plan is None:
            self._report_progress(0, 0)
            self.plan = self.make_plan()
        if self.current is None:
            self.current = self._start()
            return False
        if not self.current.join(0.05):
            return False
        worker, self.current = self.current, None
        if self._stop.is_set():
            return True
        passed, output = self._check(worker)
        if not passed:
            failed = prompts.CHECK_FAILED_PART.format(check=worker.check, output=output) if worker.check else \
                prompts.WORKER_ERROR_PART.format(error=output or "no result")
            if worker.attempt > MAX_TASK_RETRIES:
                raise RuntimeError(prompts.JOB_FAILED_PART.format(step=len(self.done) + 1, total=len(self.plan), role=worker.role,
                                                                  attempts=worker.attempt, failed=failed))
            self.trace("retry", step=len(self.done) + 1, task=worker.plan_task, role=worker.role, attempt=worker.attempt + 1, reason=failed)
            self.current = self._start(failed, worker.attempt + 1)
            return False
        self.done.append(worker)
        if len(self.done) < len(self.plan):
            return False
        attachments = self.delivery()
        self.result = {"summary": str(worker.result.get("summary") or ""), "details": self._results_text(),
                       **({"attachments": attachments} if attachments else {})}
        self.trace("result", summary=self.result["summary"], files=len(attachments))
        return True

    def _start(self, failed: str = "", attempt: int = 1) -> Worker:
        """the worker of the next step: its goal with the user's messages so far, what failed in the attempt before
        (RETRY_PART) and the results of the steps before"""
        index = len(self.done)
        task = self.plan[index]
        while not self._inbox.empty():
            self._messages.append(self._inbox.get_nowait())
        goal = task["prompt"]
        goal += prompts.USER_MESSAGES_PART.format(messages="\n".join(f"- {message}" for message in self._messages)) if self._messages else ""
        goal += prompts.RETRY_PART.format(failed=failed) if failed else ""
        context = self._results_text()
        logger.info(f"controller {self.job_id}: step {index + 1} of {len(self.plan)}: {task['role']}, attempt {attempt}")
        self._report_progress(index + 1, len(self.plan))
        if attempt == 1:
            self.trace("step_started", step=index + 1, total=len(self.plan), roles=[task["role"]])
        return self.spawn(task["role"], f"{goal}{prompts.RESULTS_MARKER_PART}{context}" if context else goal, task.get("check", ""),
                          step=index + 1, task=self.protocol.task_id(index + 1, 0), attempt=attempt)

    def _check(self, worker: Worker) -> Tuple[bool, str]:
        """(passed, output) of the worker's check in its folder (Check), the only judge of its work. without a command:
        passed unless the worker crashed (its error is the output)"""
        result = worker.result or {"error": "no result"}
        if worker.check:
            passed, output = Check(worker.check, "", worker.folder()).run(self.tool_context)
        else:
            passed, output = "error" not in result, str(result.get("error") or "")
        self.trace("check", ok=passed, step=worker.plan_step, task=worker.plan_task, command=worker.check or None, output=output or None)
        return passed, output

    def add_message(self, text: str):
        """a user message for the running job (thread-safe), the next worker's goal gets it"""
        self._inbox.put(str(text))
        self.trace("user_message", step=len(self.done) + 1 if self.plan else None, text=str(text))

    @staticmethod
    def _strict_json(text: Optional[str]):
        """the json object of an llm reply (its text around it, e.g. a code fence, is ignored), None if it is not valid
        json. unlike Utils.json_loads no repair: a repaired plan can lose the end of a task's prompt"""
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        try:
            return json.loads(match.group(0)) if match else None
        except ValueError:
            return None

    @staticmethod
    def _cut_off(reply: str) -> bool:
        """a guess that the reply ended early (token limit, context or timeout): an open ``` fence or more { than }.
        the node knows llama.cpp's finish_reason "length", but infrastructure.chat only returns the text"""
        return reply.count("```") % 2 == 1 or reply.count("{") > reply.count("}")

    def make_plan(self) -> List[Dict[str, str]]:
        """the steps from one llm call, and the job's folder (_choose_folder). no usable plan (also invalid json): one
        step, one worker does the whole job"""
        fallback = [{"role": "worker", "prompt": self.prompt, "check": ""}]
        known = self._projects()
        reply = self.chat([{"role": "user", "content": prompts.PLAN_PROMPT.format(
            prompt=self.prompt, max_steps=MAX_STEPS, projects=BashTool.projects_text(known))}], 0.2)
        data = self._strict_json(reply)
        plan = self._valid_plan(data)
        name = str(data.get("name") or "").strip() if isinstance(data, dict) else ""
        if name:
            self.name = short_name(name)
        if plan is None:
            reason = "no reply" if not reply else ("truncated" if self._cut_off(reply) else "invalid json") if data is None \
                else "not a usable plan"
            logger.warning(f"controller {self.job_id}: {reason}, one worker does the whole job. reply: {str(reply)[:300]}")
            fallback = self._choose_folder({}, known, fallback)
            self.protocol.set_plan(self.name, [[task] for task in fallback])
            self.trace("plan", ok=False, revision=0, steps=1, tasks=1, fallback=True, reason=reason, reply=reply or None)
            return fallback
        plan = self._choose_folder(data.get("project"), known, plan)
        logger.info(f"controller {self.job_id}: plan {[task['role'] for task in plan]}")
        self.protocol.set_plan(self.name, [[task] for task in plan])
        self.trace("plan", revision=0, steps=len(plan), tasks=len(plan), fallback=False)
        return plan

    def _projects(self) -> Optional[List[tuple]]:
        """the contact's projects [(folder, first line of its PROJECT.md)] (SandboxVolume.projects), None without tools
        or when they can't be read"""
        if not self.tool_context:
            return None
        try:
            return SandboxVolume(self.tool_context["user_id"], self.tool_context["contact_id"]).projects()
        except Exception as e:
            logger.warning(f"controller {self.job_id}: projects not listed {repr(e)}")
            return None

    def folder(self) -> str:
        """the job's folder below MOUNT_PATH, "" before the plan or without tools"""
        return self._folder

    def _choose_folder(self, project, known: Optional[List[tuple]], plan: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """the job's one folder, decided before any worker starts. the plan's "project" {"mode": new|continue|none, "name"}
        new: a free folder of that name (SandboxVolume.reserve_project); else a listed project (known) the job or its
        plan names by its path (~/projects/<folder>), the one the plan continues, the only one whose name is a word of
        the job, or for a job on files (file_task) the one the conversation works in (_current_project); else the
        conversation's workdir. a continue with a folder that is not listed gets a new one. returns the plan, the
        project folder it named replaced by the one the job got (_renamed)"""
        project = project if isinstance(project, dict) else {}
        mode, name = str(project.get("mode") or "none").strip().lower(), str(project.get("name") or "").strip()
        folders = [folder for folder, _ in known or []]
        texts = [self.prompt] + [task[key] for task in plan for key in ("prompt", "check")]
        named = [folder for text in texts for folder in NAMED_PROJECT.findall(text) if folder in folders]
        words = [folder for folder in folders if re.search(rf"(?<![\w.-]){re.escape(folder)}(?![\w-])", self.prompt)]
        if named and not (mode == "new" and name):
            mode, name = "continue", named[0]
        elif mode not in ("new", "continue") or not name:
            current = self._current_project() if any(file_task(text) for text in texts) else ""
            mode, name = ("continue", words[0]) if len(words) == 1 else ("continue", current) if current in folders else ("none", "")
        if not self.tool_context:
            return plan
        volume = SandboxVolume(self.tool_context["user_id"], self.tool_context["contact_id"])
        if mode == "none":
            self._folder = volume.workdir(self.tool_context["conversation_id"]).removeprefix(MOUNT_PATH + "/")
            self.trace("project", mode="none", folder=self._folder)
            return plan
        wanted = volume.project_name(name)
        folder = wanted if mode == "continue" and wanted in folders else None
        if folder is None:
            try:
                folder = volume.reserve_project(wanted)
            except Exception as e:
                logger.error(f"controller {self.job_id}: no project folder for {wanted} {repr(e)}")
                self.trace("project", ok=False, mode=mode, wanted=name, error=repr(e))
                return self._choose_folder({}, [], plan)     # the workdir
        self._folder = f"{PROJECTS}/{folder}"
        self._renaming = (wanted, folder) if folder != wanted else None
        logger.info(f"controller {self.job_id}: project {mode} {name!r} -> {folder}")
        self.trace("project", mode=mode, wanted=name, folder=self._folder, new=mode == "new" or wanted not in folders)
        return self._renamed(plan)

    def _current_project(self) -> str:
        """the project folder the conversation's bash is in (SandboxVolume.current_dir below PROJECTS), "" outside one,
        without tools or when it can't be read"""
        if not self.tool_context:
            return ""
        try:
            path = SandboxVolume(self.tool_context["user_id"], self.tool_context["contact_id"]).current_dir(
                self.tool_context["conversation_id"]).split("/")
        except Exception as e:
            logger.warning(f"controller {self.job_id}: current folder not read {repr(e)}")
            return ""
        return path[1] if len(path) > 1 and path[0] == PROJECTS else ""

    def _renamed(self, plan: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """the plan with the project folder the planner named (~/projects/<name>, MOUNT_PATH/projects/<name>) replaced by
        the one the job got (_choose_folder), as it is when they are the same"""
        if not self._renaming:
            return plan
        wanted, folder = self._renaming
        named = re.compile(rf"((?:~|{re.escape(MOUNT_PATH)})/{re.escape(PROJECTS)}/){re.escape(wanted)}(?![\w.-])")
        return [{**task, **{key: named.sub(rf"\g<1>{folder}", task[key]) for key in ("prompt", "check")}} for task in plan]

    @staticmethod
    def _valid_plan(plan) -> Optional[List[Dict[str, str]]]:
        """{"steps": [{role, goal, check}, ...]} as the steps {role, prompt (the goal), check}, None
        if it is empty, too big or not in that form. a step written as a list of tasks gives one step per task"""
        steps = plan.get("steps") if isinstance(plan, dict) else None
        if not isinstance(steps, list):
            return None
        tasks = [task for step in steps for task in (step if isinstance(step, list) else [step])]
        if not 0 < len(tasks) <= MAX_STEPS or not all(isinstance(task, dict) and str(task.get("goal") or "").strip() for task in tasks):
            return None
        return [{"role": str(task.get("role") or "worker").strip()[:40] or "worker", "prompt": str(task["goal"]).strip(),
                 "check": str(task.get("check") or "").strip()} for task in tasks]

    def _report_progress(self, step: int, total: int):
        if self.progress:
            try:
                self.progress(self.name, step, total)
            except Exception as e:
                logger.warning(f"controller {self.job_id}: progress failed {repr(e)}")

    def _results_text(self) -> str:
        """the results of the finished steps as text, each with its check (CHECKED_PART, NOT_CHECKED_PART), the newest
        kept if it is too long"""
        parts = [f"step {index}, {worker.role}:\n{Worker.result_text(worker.result)}\n"
                 f"{prompts.CHECKED_PART.format(check=worker.check) if worker.check else prompts.NOT_CHECKED_PART}"
                 for index, worker in enumerate(self.done, 1)]
        return "\n\n".join(parts)[-MAX_CONTEXT_CHARS:]

    def delivery(self) -> List[Dict[str, Any]]:
        """the files the job gives the user, also a failed job (its partial files): what its workers' tools held (an
        image, a written text, audio; a later one of the same name replaces the earlier) and the files of its folder:
        those the job names that are there (_named_files), else the ones its workers changed, no build output (BUILT),
        at most MAX_DELIVERED"""
        held = {}
        for worker in self.workers:
            for item in worker.attachments:
                key = (item.get("tool"), item.get("name"))
                held.pop(key, None)
                held[key] = item
        changed = [path.removeprefix(MOUNT_PATH + "/") for worker in self.workers for path in (worker.result or {}).get("changed") or []]
        changed = list(dict.fromkeys(path for path in changed if not BUILT.search(path)))
        folder = self._folder
        files = [{"tool": "share_file", "name": posixpath.relpath(path, folder) if folder else posixpath.basename(path), "path": path,
                  "sandbox": True} for path in (self._named_files() or changed)[:MAX_DELIVERED]]
        delivered = list(held.values()) + [item for item in files if ("share_file", item["name"]) not in held]
        self.trace("delivery", files=[item.get("name") for item in delivered])
        return delivered

    def _named_files(self) -> List[str]:
        """the files of the job's folder (below MOUNT_PATH) the job names (NAMED_FILE), in the order it names them, []
        without a folder or when it can't be read"""
        names = list(dict.fromkeys(NAMED_FILE.findall(self.prompt)))
        if not names or not self._folder or not self.tool_context:
            return []
        try:
            paths = SandboxVolume(self.tool_context["user_id"], self.tool_context["contact_id"]).stats(self._folder)
        except Exception as e:
            logger.warning(f"controller {self.job_id}: folder files not read {repr(e)}")
            return []
        return [path for name in names for path in paths if path == f"{self._folder}/{name}" or path.endswith(f"/{name}")]
