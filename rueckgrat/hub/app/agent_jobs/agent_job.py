import random
import threading
import time
from typing import Optional, Dict, Any
from uuid import uuid4

from app.common import get_logger, ChatRequest
logger = get_logger()

DEFAULT_TIME_LIMIT = 1800     # seconds, backstop: an agent that never ends its work is stopped after this

MAX_TOOL_CHARS = 12000     # the tool results in the worker's prompt
# not for workers: workers don't spawn agents, don't write the user's memories (their prompt is the planner's, not the
# user's words) and make no images or polls (those belong to a chat message)
WORKER_EXCLUDED_TOOLS = ("spawn_job", "remember", "generate_image", "take_photo", "poll")
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
    the role is fixed when the agent is made, the Controller (the first agent) sets it for its workers"""

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
        if self.infrastructure is None:
            raise RuntimeError(f"{self.role} agent has no llm (infrastructure)")
        tools = self._use_tools() if self.tool_context else ""
        text = (self.infrastructure.chat(messages=[{"role": "user", "content": WORKER_PROMPT.format(role=self.role, prompt=self.prompt, tools=tools)}],
                                         temperature=0.3, seed=random.randint(0, 100000)) or "").strip()
        if not text or text.upper().startswith("FAILED"):
            self.result = {"error": text or "no reply from the llm"}
        else:
            self.result = {"summary": text, "details": ""}
        return True

    def _use_tools(self) -> str:
        """the tool part of MetaTask.execute on this thread: tool detection (laya), tool directing (the llm writes the calls),
        the synchronous tools run (their sub jobs, e.g. FindAnswerTask, go to the TaskQueue) and their results become the
        WEBSEARCH_RESULT / CONVERSION_RESULT / TOOL_RESULT blocks. a failed tool fails the worker"""
        from app.tasks import ToolDetectionTask, ToolDirectingTask, MetaTask     # here: app.tasks imports the tools package, that imports this one
        context = self.tool_context
        registry = context["tool_registry"]
        task, _, earlier = self.prompt.partition(RESULTS_MARKER)
        # the worker's own task only: the links in the earlier results would select fetch_url every time
        detection = ToolDetectionTask(task, registry, self.infrastructure)
        registry.task_queue.run(detection)
        tool_names = [name for name in dict.fromkeys((detection.result() or []) + WORKER_TOOLS + registry.PROMPT_TOOLS) if name not in WORKER_EXCLUDED_TOOLS]
        logger.info(f"agent {self.role} {self.job_id}: tools {tool_names}")

        request = ChatRequest(contact_id=context["contact_id"], conversation_id=context["conversation_id"], role="user",
                              name=context["user_name"], content=self.prompt, temperature=0.3)
        directing = ToolDirectingTask(request=request, db=context["db"], infrastructure=self.infrastructure, tool_registry=registry, tool_names=tool_names)
        registry.task_queue.run(directing)
        directed = directing.result()
        if not directed:
            raise RuntimeError("tool directing failed")
        tool_calls = [call for call in directed["tool_calls"] or [] if call["tool"] not in WORKER_EXCLUDED_TOOLS]

        self.response = {}      # the tools write their results here, like into MetaTask.response
        registry.execute(user_id=context["user_id"], contact_id=context["contact_id"], conversation_id=context["conversation_id"],
                         response=self.response, tool_calls=tool_calls, parallel=False)
        errors = [f"{r.get('tool', 'tool')}: {r['error']}" for r in self.response.get("tool_results", []) if "error" in r]
        if any(call["tool"] == "websearch" for call in tool_calls) and not self.response.get("websearch_results"):
            if earlier:     # the steps before found something, the worker goes on with that
                logger.info(f"agent {self.role} {self.job_id}: websearch found nothing, going on with the earlier results")
            else:
                errors.append("websearch: no results")
        if errors:
            raise RuntimeError(f"tool failed: {'; '.join(errors)}")

        # MetaTask's formatting, it only reads and pops self.response
        compiled = directed["content"] or ""
        compiled += MetaTask._format_websearch_results(self) or \
            "\n\nNo web search was done for this message. If you don't know current facts like opening hours, prices or news, say so.\n"
        compiled += MetaTask._format_conversion_results(self) or ""
        compiled += MetaTask._format_tool_results(self) or ""
        return compiled[:MAX_TOOL_CHARS]

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
