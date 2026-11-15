import sys
import json
import random
import re
import threading
import time
from typing import Optional, Dict, Any
from uuid import uuid4

from . import prompts

from app.common import get_logger, ChatRequest, MessageQueue
from app.utils.trace import Trace
logger = get_logger()

DEFAULT_TIME_LIMIT = 5400     # max time for a job in seconds
JOB_LLM_TIMEOUT = 900         # seconds per llm call
MAX_TOOL_CHARS = 12000        
WORKER_TOOLS = ["websearch"]   # always run for a worker, the controller's task sets its role and scope (not for a building worker, see BUILD_TOOLS)
FAILED_LINE = re.compile(r"^\W*FAILED:", re.MULTILINE)    # a worker's reply with a line starting FAILED: failed, also mid-reply
WORKER_FIX_ROUNDS = 3          # a worker's extra passes of bash / run_code / share_file / write_file while their calls fail (ToolExecutionTask._fix)

class AgentJob:
    # never offered besides the registry's WORKER_EXCLUDED_TOOLS. a worker takes no photos: take_photo is an optional
    # tool in every tool prompt, a job would take them for nothing
    EXCLUDED_TOOLS = ("take_photo",)
    # a worker whose detection found one of these builds or tests something from its task: WORKER_TOOLS' websearch is not
    # forced on it (it searched for nothing useful, about a minute each), it still searches when its detection picks websearch
    BUILD_TOOLS = ("bash", "run_code", "write_file")
    _turns = None           # the hub's Turns, see set_turns
    connections = None      # user_id -> open /ws connections

    @classmethod
    def set_turns(cls, turns):
        """the hub's Turns (main.py at start), for jobs that wait until a reply being made is done before they post"""
        cls._turns = turns

    @classmethod
    def get_turns(cls):
        """the hub's Turns, None before the hub started (tests)"""
        return cls._turns

    def __init__(self, role: str, prompt: str, job_id: Optional[str] = None, time_limit: float = DEFAULT_TIME_LIMIT, infrastructure=None,
                 tool_context: Optional[Dict[str, Any]] = None):
        self._role = role
        self.time_limit = time_limit
        self.timed_out = False
        self.prompt = prompt
        self.job_id = job_id or uuid4().hex
        self.result: Optional[Dict[str, Any]] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.infrastructure = infrastructure    # the llm, the Controller hands its own to its workers
        # the tools, like MetaTask: {tool_registry, db, user_id, contact_id, conversation_id, user_name} of the job's conversation. None: no tools
        self.tool_context = tool_context
        self.protocol = None    # #174 the job's Protocol, the Controller makes it and hands it to its workers. None: no trace
        self.plan_step, self.plan_task = None, None   # a worker's step and task id in the plan, set by Controller.spawn
        self.attempt = 1        # a retried task's worker: 2, ... (Controller._retry)
        self.attachments = []   # a worker's files its tools held (write_file, share_file, generate_image), they go into its result
        self.excluded_tools = ()    # a retried task's worker: the tools that failed the attempts before (Controller._retry)
        self.failed_tools = []      # the tools that failed or found nothing in this worker's run, a failed result names them

    def trace(self, action: str, ok=None, step=None, task=None, **data):
        """#174 one line of this agent in the job's protocol, by default in its own step and task"""
        if self.protocol is not None:
            if self.attempt > 1:
                data.setdefault("attempt", self.attempt)
            self.protocol.add(self.role, self.job_id, action, self.plan_step if step is None else step, self.plan_task if task is None else task, ok, **data)

    @property
    def role(self) -> str:
        return self._role

    def run(self) -> Optional[Dict[str, Any]]:
        deadline = time.monotonic() + self.time_limit
        while not self._stop.is_set():
            if time.monotonic() >= deadline:
                self.timed_out = True
                self.result = {"error": "timed_out", "details": f"{self.role} agent stopped after its time limit of {self.time_limit}s"}
                logger.warning(f"agent {self.role} {self.job_id} timed out after {self.time_limit}s")
                self.trace("timed_out", ok=False, limit=self.time_limit)
                self.stop()
                break
            if self.step():
                break
        return self.result

    def step(self) -> bool:
        """one pass of working out the current task. returns True when the agent is done.
        a worker runs the tools its task needs (like MetaTask), then does its task in one llm call with their results"""
        tools = self._use_tools() if self.tool_context else ""
        text = self.chat([{"role": "user", "content": prompts.WORKER_PROMPT.format(role=self.role, prompt=self.prompt, tools=tools)}], 0.3).strip()
        if not text or FAILED_LINE.search(text):
            self.result = {"error": text or "no reply from the llm", **({"failed_tools": self.failed_tools} if self.failed_tools else {})}
        else:
            self.result = {"summary": text, "details": "", **({"attachments": self.attachments} if self.attachments else {})}
        self.trace("done", ok="error" not in self.result, **({"error": text or "no reply"} if "error" in self.result else {"summary": text}))
        return True

    def _use_tools(self) -> str:
        """a worker's tools (run_tools) and their results as the TOOL_RESULTS block. a failed tool or a search that found
        nothing does not fail the worker: the block says so, the worker decides if it can do its task anyway
        (else it replies FAILED, its result names the failed tools for the retry, see Controller._retry)"""
        task, _, earlier = self.prompt.partition(prompts.RESULTS_MARKER_PART)
        # the worker's own task only: the links in the earlier results would select fetch_url every time
        execution = self.run_tools(task, self.prompt, WORKER_TOOLS, optional_when=self.BUILD_TOOLS)
        results = execution.get_result()
        self.attachments = [held for result in results.values() if isinstance(result, dict) for held in result.get("attachments") or []]

        failed = [f"{name} ({result['error']})" for name, result in results.items() if isinstance(result, dict) and "error" in result]
        self.failed_tools = [name for name, result in results.items() if isinstance(result, dict) and "error" in result]
        searched = any(entry["call"]["tool"] == "websearch" for entry in execution.executed)
        empty_search = searched and "websearch" not in results
        if empty_search:
            self.failed_tools.append("websearch")
            logger.info(f"agent {self.role} {self.job_id}: websearch found nothing, the worker goes on without it")
        if failed:
            logger.warning(f"agent {self.role} {self.job_id}: tools failed {'; '.join(failed)}")

        text = execution.results_prompt(results)
        if empty_search:
            text = prompts.EMPTY_WEBSEARCH_PART + text
        elif "websearch" not in results:
            text = prompts.NO_WEBSEARCH_PART + text
        if failed:
            text = prompts.FAILED_TOOLS_PART.format(failed="; ".join(failed)) + text
        return text[:MAX_TOOL_CHARS]

    def run_tools(self, detect: str, query: str, always: list, optional_when=()):
        """detects and runs the tools of detect. always: run in any case, unless the detection found one of optional_when"""
        from app.tasks import ToolDetectionTask, ToolExecutionTask
        context = self.tool_context
        registry = context["tool_registry"]
        excluded = registry.WORKER_EXCLUDED_TOOLS + self.EXCLUDED_TOOLS + tuple(self.excluded_tools)
        detection = ToolDetectionTask(detect, registry, self.infrastructure, excluded_tools=excluded)
        registry.task_queue.run(detection)
        detection.trace(context["conversation_id"], f"{self.role} {self.job_id}")
        detected = (detection.get_result() or {}).get("tool_names") or []
        recommended = (detection.get_result() or {}).get("recommended") or []
        if any(name in detected for name in optional_when):
            always = [name for name in always if name in detected]

        request = ChatRequest(
            contact_id=context["contact_id"], 
            conversation_id=context["conversation_id"], 
            role="user",
            name=context["user_name"], 
            content=query, 
            temperature=0.3
        )

        execution = ToolExecutionTask(
            user_id=context["user_id"], 
            request=request, 
            context=None, 
            db=context["db"],
            infrastructure=self.infrastructure, 
            tool_registry=registry, 
            tool_names=detected + list(always),
            excluded_tools=excluded, llm_timeout=JOB_LLM_TIMEOUT, recommended_tools=recommended,
            fix_rounds=WORKER_FIX_ROUNDS
        )
        
        logger.info(f"agent {self.role} {self.job_id}: tools {execution.tool_names}, recommended {execution.recommended}, detected {detected}")
        self.trace("tools", tools=execution.tool_names, recommended=execution.recommended or None, detected=detected)
        Trace.write(context["conversation_id"], f"tools of {self.role} {self.job_id}", f"TOOL SETUP QUERY:\n{query}",
                    mandatory=execution.tool_names, recommended=execution.recommended, detected=detected, always=list(always),
                    rounds=registry.rounds(execution.tool_names, execution.recommended), excluded=list(excluded))
        registry.task_queue.run(execution)
        self._trace_calls(execution)
        return execution

    def _trace_calls(self, execution):
        if self.protocol is None:
            return
        
        results = execution.get_result()
        for entry in execution.executed:
            call = entry["call"]
            tool = call.get("tool")
            result = results.get(tool)
            errors = [str(result["error"])] if isinstance(result, dict) and "error" in result else []

            if tool == "websearch" and result is None:
                errors.append("no results")

            self.protocol.tool_call(self.role, self.job_id, self.plan_step, self.plan_task, tool,
                                    json.dumps({k: v for k, v in call.items() if k != "tool"}, ensure_ascii=False, default=str),
                                    not errors, "; ".join(errors) or None, entry["ms"], self.attempt if self.attempt > 1 else None)

    def chat(self, messages: list, temperature: float) -> str:
        """one llm call, "" without a reply"""
        if self.infrastructure is None:
            raise RuntimeError(f"{self.role} agent has no llm (infrastructure)")
        started, info = time.monotonic(), {}
        reply = self.infrastructure.chat(messages=messages, temperature=temperature, seed=random.randint(0, 100000),
                                         max_new_tokens=self.infrastructure.long_reply_tokens(), timeout=JOB_LLM_TIMEOUT, info=info) or ""
        # the trace names the caller (make_plan, _review, _retry, _merge, step: the worker's summary, _report)
        Trace.write((self.tool_context or {}).get("conversation_id"), f"llm {self.role} {sys._getframe(1).f_code.co_name}",
                    f"{Trace.messages(messages)}\n----- reply -----\n{reply}", agent=self.job_id, temperature=temperature,
                    chars=len(reply), seconds=f"{time.monotonic() - started:.1f}", **info)
        return reply

    @staticmethod
    def user_name(db, user_id: int) -> str:
        """how the user is called (their profile), "the user" without a name"""
        try:
            name = json.loads((db.get_user_data(user_id) or {}).get("profile") or "{}").get("name")
        except Exception:
            name = None
        return name or "the user"

    @staticmethod
    def persona_messages(contact: dict, conversation: dict, user_name: str, task: str) -> list:
        """the contact's persona (PromptCompiler, same as chat) and the job's task for it"""
        from app.utils.prompt_compiler import PromptCompiler
        system_prompt, _ = PromptCompiler(contact=contact, conversation=conversation, user_role_name=user_name).build_prompt()
        return [
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": task},
        ]

    @classmethod
    def user_connected(cls, user_id: int) -> bool:
        return cls.connections is not None and cls.connections[user_id] > 0

    @classmethod
    def post_message(cls, db, user_id: int, conversation_id: int, text: str, name: str) -> tuple[int, bool]:
        """stores text as the contact's message like a normal reply, so later replies see it in the history, and pushes
        it when the user is connected. returns (message_id, pushed)"""
        message_id = db.add_message(conversation_id, "assistant", text, name)
        pushed = cls.user_connected(user_id)
        if pushed:
            MessageQueue().send_data({"chat": {
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": text,
                "tool_calls": [],
                "message_id": message_id
            }}, user_id=user_id)   # only the conversation's owner
        return message_id, pushed

    def stop(self):
        self._stop.set()

    def start(self):
        """runs the loop on its own thread"""
        self._thread = threading.Thread(target=self._run_safe, daemon=True, name=f"agent-{self.role}-{self.job_id[:8]}")
        self._thread.start()

    def join(self, timeout: Optional[float] = None) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run_safe(self):
        try:
            self.run()
        except Exception as e:
            logger.error(f"agent {self.role} {self.job_id} failed {repr(e)}")
            self.result = {"error": repr(e)}
            self.trace("failed", ok=False, error=repr(e))
