import sys
import json
import random
import threading
import time
from typing import Optional, Dict, Any
from uuid import uuid4

from app.common import get_logger, MessageQueue
from app.utils.trace import Trace
logger = get_logger()

DEFAULT_TIME_LIMIT = 28800    # max time for a job in seconds (8 h: the controller), speaking a long work takes hours
JOB_LLM_TIMEOUT = 1800        # seconds per llm call, a setup round writing eight chapters takes over 12 minutes

class AgentJob:
    """an agent on its own thread with a time limit (run: step() until it is done). the base of a job's Controller and
    its workers (Worker), and of the task and companion passes (TaskJob, CompanionJob): llm calls (chat), decision trace
    (trace) and messages (post_message). only a Worker calls tools: a job's controller spawns them, a pass runs one for
    its lookup (worker.lookup)"""
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
        self.attachments = []   # the files its tools held (write_file, share_file, generate_image) for its result or message
        self.held_data = {}     # {kind: value} its tools held for a message (ToolRegistry.show_held): a pass's lookup
        self.deadline = None    # time.monotonic() when its time limit is up (run)

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
        self.deadline = time.monotonic() + self.time_limit
        while not self._stop.is_set():
            if time.monotonic() >= self.deadline:
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
        """one pass of the agent's work, True when it is done (its result set)"""
        raise NotImplementedError

    def trace_call(self, call: Dict[str, Any], error: Optional[str], ms: int) -> None:
        """#174 one tool call of this agent in the job's protocol, error None: it worked"""
        if self.protocol is not None:
            self.protocol.tool_call(self.role, self.job_id, self.plan_step, self.plan_task, call.get("tool"),
                                    json.dumps({k: v for k, v in call.items() if k != "tool"}, ensure_ascii=False, default=str),
                                    error is None, error, ms, self.attempt if self.attempt > 1 else None)

    def chat(self, messages: list, temperature: float, json_schema: Optional[dict] = None, timeout: float = JOB_LLM_TIMEOUT) -> str:
        """one llm call, "" without a reply. json_schema: the reply is json of that schema (the node's grammar)"""
        if self.infrastructure is None:
            raise RuntimeError(f"{self.role} agent has no llm (infrastructure)")
        started, info = time.monotonic(), {}
        reply = self.infrastructure.chat(messages=messages, temperature=temperature, seed=random.randint(0, 100000),
                                         max_new_tokens=self.infrastructure.long_reply_tokens(), timeout=timeout,
                                         json_schema=json_schema, info=info) or ""
        # the trace names the caller (make_plan, _ask: a worker's turn, _report)
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
    def post_message(cls, db, user_id: int, conversation_id: int, text: str, name: str, alarm: bool = False) -> tuple[int, bool]:
        """stores text as the contact's message like a normal reply, so later replies see it in the history, and pushes
        it when the user is connected. alarm: the app rings (a user's task with its alarm on). returns (message_id, pushed)"""
        message_id = db.add_message(conversation_id, "assistant", text, name)
        pushed = cls.user_connected(user_id)
        if pushed:
            chat = {
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": text,
                "tool_calls": [],
                "message_id": message_id
            }
            if alarm:
                chat["alarm"] = True
            MessageQueue().send_data({"chat": chat}, user_id=user_id)   # only the conversation's owner
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
