import threading
import time
from typing import Dict, Any
from uuid import uuid4
from .tool import Tool, ToolCategory
from app.agent_jobs.agent_job import AgentJob
from app.agent_jobs.controller import Controller, short_name

from app.common import get_logger, Utils, MessageQueue
logger = get_logger()

REPORT_PROMPT = """A background job you started for the user has finished.

JOB_PROMPT:
{prompt}

JOB_RESULT:
{summary}
{details}

Tell the user in one or two short sentences that the job is done and what it found. Reply with the message only.
"""

CANCEL_PROMPT = """The user cancelled a background job you started for them, it was stopped before it finished.

JOB_PROMPT:
{prompt}

Tell the user in one or two short sentences that the job "{name}" is stopped, and react to the cancel as it fits the conversation. Reply with the message only.
"""

FAIL_PROMPT = """A background job you started for the user has failed, it stopped before it was finished.

JOB_PROMPT:
{prompt}

WHY IT FAILED:
{reason}

Tell the user in one or two short sentences that the job "{name}" failed and why, in plain words. Reply with the message only.
"""
FAIL_REASON_CHARS = 300     # the failure as the contact gets it, the full one is in the protocol

class SpawnAgentJobTool(Tool):
    """#152 starts a background job: a Controller agent plans it and runs its workers (app.agent_jobs).
    the contact then tells the user about the result in a new message of the same conversation"""
    category = ToolCategory.GENERAL
    description = "hands a task to a background job: long or multi-step work, research with its own analysis, watching something, or repeating on a schedule and reporting back later"
    # the user tells the ai to do it, not talks about background jobs, agents or tools (scored on laya, /tmp/rg_spawnq)
    question = [
        "Is the user commanding you to put a task in the background?",
        "Is the user asking you to research something on your own and report back later?",
        "Is the user telling you to monitor something and alert them when it changes?"
    ]

    # set at hub start (main.py). the report waits while a reply is being made (AgentJob.turns)
    # and is pushed only to a user with an open /ws (AgentJob.connections), it is in the db anyway
    tool_registry = None    # the workers' tools
    running: Dict[str, "SpawnAgentJobTool"] = {}    # job_id -> the tool of a running job: cancel, the user's messages
    running_lock = threading.Lock()

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "spawn_job"

    def execute(self) -> None:
        prompt = str(self.tool_call.get("prompt") or "").strip()
        job_id = uuid4().hex     # the one id of this job: jobs.id, the tool result and the logs use this same value
        with self.running_lock:     # one job per conversation: the check and the start in one go
            current = self._running_in(self.user_id, self.conversation_id)
            if current is None:
                try:
                    saved = self.db.add_job(job_id, prompt, self.conversation_id)
                except Exception as e:
                    saved = False
                    logger.error(f"spawn_job: job {job_id} not saved {repr(e)}")
                if saved:
                    self.job_id, self.cancelled = job_id, False
                    self.message_id = self._message_id()    # #174 the protocol's key: the user message that started the job
                    tool_context = {"tool_registry": self.tool_registry, "db": self.db, "user_id": self.user_id, "contact_id": self.contact_id,
                                    "conversation_id": self.conversation_id, "user_name": AgentJob.user_name(self.db, self.user_id)} if self.tool_registry else None
                    self.controller = Controller(prompt, job_id, infrastructure=self.infrastructure, progress=self._progress, tool_context=tool_context)
                    self.running[job_id] = self
        if current is not None:
            # the user's message is in its inbox already (main.py, add_message), the job's next review reads it
            logger.info(f"spawn_job: job {current.job_id} runs in conversation {self.conversation_id}, no second job")
            self.response.setdefault("tool_results", []).append({"tool": self.name(), "job_id": current.job_id,
                "text": "a job is running in this conversation already, it got the user's message and adjusts its plan after its current step"})
            return
        if not saved:
            self.response.setdefault("tool_results", []).append({"tool": self.name(), "job_id": job_id, "error": "the job could not be started"})
            return

        threading.Thread(target=self._run, args=(job_id, prompt), daemon=True, name=f"job-{job_id[:8]}").start()
        logger.debug(f"spawn_agent_job id:{job_id} started, prompt: {prompt}")
        self.response.setdefault("tool_results", []).append({"tool": self.name(), "job_id": job_id, "text": "the job was started, it reports back when it is done"})

    def _run(self, job_id: str, prompt: str):
        self._job = {"job_id": job_id, "name": short_name(prompt), "percent": 0, "step": 0, "total": 0}    # the last progress sent
        failure = None
        try:
            self.db.set_job(job_id, "running")
            try:
                result = self.controller.run()
            finally:
                with self.running_lock:
                    self.running.pop(job_id, None)     # no cancel and no messages any more
            if not self.cancelled:
                if not result or "error" in result:
                    raise RuntimeError(f"agent failed: {result}")
                if not self.db.set_job(job_id, "done", result):
                    raise RuntimeError("result not saved")
                logger.info(f"job {job_id} done")
                self._save_protocol("done")
        except Exception as e:
            if not self.cancelled:     # a cancel can also end in an error, e.g. of a stopped worker
                logger.error(f"job {job_id} failed {repr(e)}")
                self.db.set_job(job_id, "failed")
                self._save_protocol("failed", repr(e))
                self._send_progress(state="failed")
                failure = " ".join(str(e).split())
        if failure is not None:     # the contact tells the user, like a done or cancelled job
            name = self.controller.name
            reason = failure if len(failure) <= FAIL_REASON_CHARS else failure[:FAIL_REASON_CHARS - 1] + "…"
            task, fallback = FAIL_PROMPT.format(prompt=prompt, name=name, reason=reason), f'The background job "{name}" failed: {reason}'
        elif self.cancelled:
            logger.info(f"job {job_id} cancelled by the user")
            self.db.set_job(job_id, "cancelled", {"error": "cancelled", "details": "cancelled by the user"})
            self._save_protocol("cancelled")
            self._send_progress(state="cancelled")
            name = self.controller.name
            task, fallback = CANCEL_PROMPT.format(prompt=prompt, name=name), f'The background job "{name}" is cancelled.'
        else:
            self._send_progress(state="done", percent=100)
            task = REPORT_PROMPT.format(prompt=prompt, summary=result["summary"], details=result["details"])
            fallback = f"The background job is done: {result['summary']}"
        try:
            self._report(task, fallback)
        except Exception as e:
            logger.error(f"job {job_id}: report failed {repr(e)}")

    def _message_id(self):
        """the conversation's last user message when the job starts (it is stored before the tools run), None if not found"""
        try:
            return self.db.last_user_message_id(self.conversation_id)
        except Exception as e:
            logger.error(f"spawn_job: no user message for the protocol {repr(e)}")
            return None

    def _save_protocol(self, status: str, error: str = None):
        """#174 the job's decision trace into the db (job_protocols), keyed by the conversation and the user message that
        started the job. it never fails the job"""
        try:
            controller = self.controller
            controller.trace("job_finished", ok=status == "done", status=status, name=controller.name,
                             **controller.protocol.counts(controller.job_id), error=error)
            if controller.protocol.plan:
                controller.protocol.plan["name"] = controller.name     # a review may have renamed the job
            if self.message_id is None:
                logger.warning(f"job {self.job_id}: protocol not saved, no user message")
                return
            self.db.save_protocol(self.conversation_id, self.message_id, self.job_id, controller.protocol.export())
        except Exception as e:
            logger.error(f"job {self.job_id}: protocol not saved {repr(e)}")

    @classmethod
    def _running_in(cls, user_id: int, conversation_id: int):
        """the running job of the conversation or None. with running_lock held"""
        return next((tool for tool in cls.running.values() if tool.user_id == user_id and tool.conversation_id == conversation_id), None)

    @classmethod
    def add_message(cls, user_id: int, conversation_id: int, text: str) -> bool:
        """a user message of the conversation goes to its running job too, the job's review after its current step decides
        if it changes the plan. False: no job running there"""
        with cls.running_lock:
            tool = cls._running_in(user_id, conversation_id)
            if tool is not None:
                tool.controller.add_message(text)
        return tool is not None

    @classmethod
    def cancel(cls, user_id: int, job_id: str) -> bool:
        """the user's cancel button: stops the user's running job. its thread saves it as cancelled, removes its progress
        row and the contact reacts to it. an unknown, finished or foreign job: nothing"""
        with cls.running_lock:
            tool = cls.running.get(job_id)
            if tool is None or tool.user_id != user_id:
                (logger.warning if tool else logger.debug)(f"user {user_id}: no cancel of {'foreign' if tool else 'unknown or finished'} job {job_id}")
                return False
            tool.cancelled = True
            tool.controller.trace("cancelled")
            tool.controller.stop()
        logger.info(f"job {job_id}: cancel by user {user_id}")
        return True

    def _progress(self, name: str, step: int, total: int):
        """the Controller's progress: planning (0 of 0) and every step i of n that starts. the planning counts as
        one part of the job, so step i of n is i / (n + 1) done"""
        self._send_progress(name=name, step=step, total=total, percent=round(100 * step / (total + 1)) if total else 0)

    def _send_progress(self, state: str = "running", **changes):
        """the job's progress bar in the StatusWidget (MessageQueue.send_job_progress), its own display, so also while
        a reply is being made. only to a user with an open /ws, a closed one would pile up in its queue. at the end also
        the "done" status, but not while a reply is being made (it would end the reply's status)"""
        self._job.update(changes)
        if not AgentJob.user_connected(self.user_id):
            return
        MessageQueue().send_job_progress(self._job["job_id"], self._job["name"], self._job["percent"], state,
                                         self._job["step"], self._job["total"], user_id=self.user_id)
        if state != "running" and not (AgentJob.turns and AgentJob.turns.busy(self.conversation_id)):
            MessageQueue().set_status("done", user_id=self.user_id)    # stops the spinner of the workers' tool status messages

    def _report(self, task: str, fallback: str):
        """the contact tells the user what the job found, that it failed or was cancelled (task: REPORT_PROMPT / FAIL_PROMPT / CANCEL_PROMPT):
        a new assistant message, stored and pushed like a companion message (AgentJob.post_message)"""
        contact = self.db.get_contact_by_id(self.contact_id)
        name = Utils.get_nested_value(contact, ["identity", "name"], "")
        messages = AgentJob.persona_messages(contact, self.db.get_conversation(self.conversation_id), AgentJob.user_name(self.db, self.user_id), task)
        text = self.controller.chat(messages, 0.7).strip() or fallback

        while AgentJob.turns and AgentJob.turns.busy(self.conversation_id):
            time.sleep(1)   # a reply is being made, the report comes after it
        message_id, _ = AgentJob.post_message(self.db, self.user_id, self.conversation_id, text, name)
        logger.info(f"job report sent as message {message_id}, conversation {self.conversation_id}")

    @classmethod
    def prompt(cls) -> str:
        return """
SPAWN_JOB:
Use to hand a task to a background job, so the conversation can go on meanwhile.
Use it for tasks that take long, have several steps, keep watching something, or repeat on a schedule and report back later.
A conversation has one job at a time: while it runs, the user's messages go to it and it adjusts its plan.

Parameters:
- prompt (string, required): the full instructions for the job, in the user's own words. Keep every detail the user gave: what to do, when or how often, and when to report back. Never add names, numbers, tickers or places the user did not say. If the user says "these" or "my" without naming them, keep it like that and add: ask the user which ones.

Examples:
{"tool": "spawn_job", "prompt": "find three reviews of the new Pixel phone and summarize them"}
{"tool": "spawn_job", "prompt": "every Friday check the prices of my two favourite games and message me if one is on sale (ask the user which games)"}
"""
