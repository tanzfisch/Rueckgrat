import json
import random
import threading
import time
from typing import Optional, Dict, Any
from uuid import uuid4

from app.common import get_logger, ChatRequest, MessageQueue
logger = get_logger()

DEFAULT_TIME_LIMIT = 1800     # seconds, backstop: an agent that never ends its work is stopped after this

MAX_TOOL_CHARS = 12000     # the tool results in the worker's prompt
# not for workers and companions: they don't spawn agents, don't write the user's memories (their prompt is the planner's
# or the companion's, not the user's words) and make no images, polls or maps (those belong to a chat message)
WORKER_EXCLUDED_TOOLS = ("spawn_job", "remember", "generate_image", "take_photo", "poll", "show_map")
# always in a worker's tool directing prompt, like PROMPT_TOOLS: the websearch questions of the detection are about chat
# messages (news, games, shops, opening hours), a planner's "research ..." task scores 0.0. tool directing decides the call
WORKER_TOOLS = ["websearch"]
RESULTS_MARKER = "\n\nRESULTS OF THE STEPS BEFORE:\n"    # the Controller appends the earlier results to a task after this

WORKER_PROMPT = """You are the {role} in a background job. Do your task and report what you found or made.
Facts, numbers and dates come only from the tool results below and from the task itself. Name the source of each fact as the tool results give it. Never make up facts, numbers or sources.
Stay factual and neutral: report what the sources say, also where they disagree, without taking sides.
If you can not do the task with what you have, reply with FAILED: and the reason.

YOUR TASK:
{prompt}
{tools}
Reply with the result only.
"""

class AgentJob:
    """#152 base of a spawned agent. it runs on its own thread, not on the TaskQueue:
    its loop runs until the work is done and would hold a TaskQueue worker the whole time.
    the role is fixed when the agent is made, the Controller (the first agent) sets it for its workers.
    the companion (app.companion.companion_job.CompanionJob) is one too, its scheduler runs one pass per due calendar row"""

    # set at hub start (main.py): a message of a job (a job report, a companion message) waits for or skips a reply
    # being made (turns) and is pushed only to a user with an open /ws (connections), it is in the db anyway
    turns = None
    connections = None      # user_id -> open /ws connections

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
                self.stop()
                break
            if self.step():
                break
        return self.result

    def step(self) -> bool:
        """one pass of working out the current task. returns True when the agent is done.
        a worker runs the tools its task needs (like MetaTask), then does its task in one llm call with their results"""
        tools = self._use_tools() if self.tool_context else ""
        text = self.chat([{"role": "user", "content": WORKER_PROMPT.format(role=self.role, prompt=self.prompt, tools=tools)}], 0.3).strip()
        if not text or text.upper().startswith("FAILED"):
            self.result = {"error": text or "no reply from the llm"}
        else:
            self.result = {"summary": text, "details": ""}
        return True

    def _use_tools(self) -> str:
        """a worker's tools (find_tools) and their results as the WEBSEARCH_RESULT / CONVERSION_RESULT / TOOL_RESULT blocks.
        a failed tool fails the worker"""
        task, _, earlier = self.prompt.partition(RESULTS_MARKER)
        # the worker's own task only: the links in the earlier results would select fetch_url every time
        directed = self.find_tools(task, self.prompt, WORKER_TOOLS)
        if not directed:
            raise RuntimeError("tool directing failed")
        tool_calls = directed["tool_calls"]

        errors = [f"{r.get('tool', 'tool')}: {r['error']}" for r in self.response.get("tool_results", []) if "error" in r]
        if any(call["tool"] == "websearch" for call in tool_calls) and not self.response.get("websearch_results"):
            if earlier:     # the steps before found something, the worker goes on with that
                logger.info(f"agent {self.role} {self.job_id}: websearch found nothing, going on with the earlier results")
            else:
                errors.append("websearch: no results")
        if errors:
            raise RuntimeError(f"tool failed: {'; '.join(errors)}")

        compiled = directed["content"] or ""
        compiled += self.tool_results_text(
            "\n\nNo web search was done for this message. If you don't know current facts like opening hours, prices or news, say so.\n")
        return compiled[:MAX_TOOL_CHARS]

    def find_tools(self, detect: str, query: str, always: list) -> Optional[Dict[str, Any]]:
        """the tool part of MetaTask.execute on this thread: tool detection (laya) on detect, tool directing (the llm writes
        the calls for query) with the detected tools, always and PROMPT_TOOLS, never WORKER_EXCLUDED_TOOLS. then the
        synchronous tools run (run_tools, their sub jobs, e.g. FindAnswerTask, go to the TaskQueue).
        returns the directing's {content, tool_calls}, None if the directing failed (no tools ran then)"""
        from app.tasks import ToolDetectionTask, ToolDirectingTask     # here: app.tasks imports the tools package, that imports this one
        context = self.tool_context
        registry = context["tool_registry"]
        detection = ToolDetectionTask(detect, registry, self.infrastructure)
        registry.task_queue.run(detection)
        tool_names = [name for name in dict.fromkeys((detection.result() or []) + always + registry.PROMPT_TOOLS) if name not in WORKER_EXCLUDED_TOOLS]
        logger.info(f"agent {self.role} {self.job_id}: tools {tool_names}")

        request = ChatRequest(contact_id=context["contact_id"], conversation_id=context["conversation_id"], role="user",
                              name=context["user_name"], content=query, temperature=0.3)
        directing = ToolDirectingTask(request=request, db=context["db"], infrastructure=self.infrastructure, tool_registry=registry, tool_names=tool_names)
        registry.task_queue.run(directing)
        directed = directing.result()
        if not directed:
            return None
        directed["tool_calls"] = [call for call in directed["tool_calls"] or [] if call["tool"] not in WORKER_EXCLUDED_TOOLS]
        self.run_tools(directed["tool_calls"])
        return directed

    def tool_results_text(self, no_websearch: str = "") -> str:
        """MetaTask's formatting of the results in self.response (it only reads and pops it), no_websearch without a websearch result"""
        from app.tasks import MetaTask
        return (MetaTask._format_websearch_results(self) or no_websearch) + \
            (MetaTask._format_conversion_results(self) or "") + (MetaTask._format_tool_results(self) or "")

    def chat(self, messages: list, temperature: float) -> str:
        """one llm call, "" without a reply"""
        if self.infrastructure is None:
            raise RuntimeError(f"{self.role} agent has no llm (infrastructure)")
        return self.infrastructure.chat(messages=messages, temperature=temperature, seed=random.randint(0, 100000)) or ""

    def run_tools(self, tool_calls: list) -> Dict[str, Any]:
        """the synchronous tools of the calls on this thread, for the job's conversation (tool_context).
        they write their results into self.response, like into MetaTask.response"""
        context = self.tool_context
        self.response = {}
        context["tool_registry"].execute(user_id=context["user_id"], contact_id=context["contact_id"], conversation_id=context["conversation_id"],
                                         response=self.response, tool_calls=tool_calls, parallel=False)
        return self.response

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
