import threading
import time
from typing import Dict, Any
from uuid import uuid4
from .tool import Tool
from . import prompts
from app.agent_jobs.agent_job import AgentJob, DEFAULT_TIME_LIMIT
from app.agent_jobs.controller import Controller, short_name
from app.agent_jobs.protocol import Protocol, ProtocolStore
from app.agent_jobs.job_monitor import JobMonitor, RunningJob

from app.common import get_logger, Utils, MessageQueue
from app.utils.trace import Trace
from app.utils.message_shape import MessageShape
logger = get_logger()

FAIL_REASON_CHARS = 1200    # the failure as the contact gets it, the full one is in the protocol
JOB_COMPLEXITY = 0.4        # a message whose shape (MessageShape.complexity) reaches it recommends spawn_job. t463: jobs of
                            # several steps 0.31-1.0, long but simple messages (a story, an email, a long question) at most 0.31


class SpawnAgentJobTool(Tool):
    """#152 starts a background job: a Controller agent plans it and runs its workers (app.agent_jobs).
    the contact then tells the user about the result in a new message of the same conversation"""
    description = prompts.SPAWN_JOB_DESCRIPTION
    # scored on laya (/tmp/probe_spawn.py): jobs 0.44-0.90, chat messages (a how-to with a code block, explain, a follow-up
    # question, poem, weather) at most 0.38. "commanding you to put a task in the background" took a venv how-to for a job (0.66)
    thresholds = (0.7, 0.75)    # (recommended, mandatory) for the laya questions, from laya_tune/tune.sh
    whole_message = True    # a job of several steps shows as a whole: part by part the polished audiobook request scored 0.42, whole 0.98
    question = [
        "Is the user asking you to build a complete multi-file software project?",
        "Does the user ask you to program a whole game or app?",
        "Does the user ask you to do a long task in the background while they wait?",
        "Does the user ask you to research and compare several products using reviews from the web?",
        # running code (#230, there is no tool of its own for it): a job writes and runs the program
        "Does the user want to see the output of running code?",
        "Does this message ask to verify, test, benchmark, reproduce or prototype something by running code?",
        "Does this message ask to debug or reproduce an error by running code?",
    ]

    # set at hub start (main.py). the report waits while a reply is being made (AgentJob.get_turns())
    # and is pushed only to a user with an open /ws (AgentJob.connections), it is in the db anyway
    tool_registry = None    # the workers' tools
    running: Dict[str, "SpawnAgentJobTool"] = {}    # job_id -> the tool of a running job: cancel, the user's messages
    running_lock = threading.Lock()

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, tool_call)

    @classmethod
    def name(cls) -> str:
        return "spawn_job"

    @classmethod
    def text_score(cls, prompt: str) -> float:
        """a message of several steps (MessageShape.complexity at least JOB_COMPLEXITY) recommends spawn_job, never more:
        the model decides"""
        return cls.thresholds[0] if MessageShape(prompt).complexity() >= JOB_COMPLEXITY else 0.0

    def execute(self) -> None:
        prompt = str(self.tool_call.get("prompt") or "").strip()
        job_id = uuid4().hex     # the one id of this job: jobs.id, the tool result and the logs use this same value
        with self.running_lock:     # one job per conversation: the check and the start in one go
            current = self._running_in(self.get_user_id(), self.get_conversation_id())
            if current is None:
                try:
                    saved = self.db.add_job(job_id, prompt, self.get_conversation_id())
                except Exception as e:
                    saved = False
                    logger.error(f"spawn_job: job {job_id} not saved {repr(e)}")
                if saved:
                    self.job_id, self.cancelled = job_id, False
                    self.message_id = self._message_id()    # #174 the user message that started the job, in its protocol
                    tool_context = {"tool_registry": self.tool_registry, "db": self.db, "user_id": self.get_user_id(), "contact_id": self.contact_id,
                                    "conversation_id": self.get_conversation_id(), "user_name": AgentJob.user_name(self.db, self.get_user_id())} if self.tool_registry else None
                    # #215 the protocol is stored as it happens, the Backroom shows the job live (JobMonitor)
                    protocol = Protocol(ProtocolStore.create(self.db, job_id, "job", self.get_user_id(), short_name(prompt), contact_id=self.contact_id,
                                                             conversation_id=self.get_conversation_id(), message_id=self.message_id,
                                                             time_limit=DEFAULT_TIME_LIMIT))
                    self.controller = Controller(prompt, job_id, infrastructure=self.infrastructure, progress=self._progress, tool_context=tool_context,
                                                 protocol=protocol)
                    self.running[job_id] = self
        if current is not None:
            # the user's message is in its inbox already (main.py, add_message), the job's next review reads it
            logger.info(f"spawn_job: job {current.job_id} runs in conversation {self.get_conversation_id()}, no second job")
            self.add_result({"tool": self.name(), "job_id": current.job_id,
                "text": prompts.SPAWN_JOB_RUNNING_PART})
            return
        if not saved:
            self.add_result({"tool": self.name(), "job_id": job_id, "error": "the job could not be started"})
            return
        JobMonitor().start(RunningJob(job_id, "job", self.controller.name, self.get_user_id(), self.controller.protocol, self.controller.time_limit,
                                      contact_id=self.contact_id, conversation_id=self.get_conversation_id(), cancel=self._cancel))

        threading.Thread(target=self._run, args=(job_id, prompt), daemon=True, name=f"job-{job_id[:8]}").start()
        logger.debug(f"spawn_agent_job id:{job_id} started, prompt:\n{prompt}")
        self.add_result({"tool": self.name(), "job_id": job_id, "text": prompts.SPAWN_JOB_STARTED_PART})

    def _run(self, job_id: str, prompt: str):
        failure, attachments = None, None
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
                self._end("done")
        except Exception as e:
            if not self.cancelled:     # a cancel can also end in an error, e.g. of a stopped worker
                logger.error(f"job {job_id} failed {repr(e)}")
                self.db.set_job(job_id, "failed")
                self._end("failed", repr(e))
                failure = " ".join(str(e).split())
        if failure is not None:     # the contact tells the user, like a done or cancelled job
            name = self.controller.name
            reason = failure if len(failure) <= FAIL_REASON_CHARS else failure[:FAIL_REASON_CHARS - 1] + "…"
            # the files its workers made so far go with the report, as unfinished and not checked
            attachments = self._partial_attachments()
            names = "\n".join(f"- {held['name']}" for held in attachments)
            task = prompts.SPAWN_JOB_FAILED_PROMPT.format(prompt=prompt, name=name, reason=reason,
                                                          attachments=prompts.SPAWN_JOB_PARTIAL_PART.format(names=names) if attachments else "")
            fallback = f'The background job "{name}" failed: {reason}'
        elif self.cancelled:
            logger.info(f"job {job_id} cancelled by the user")
            self.db.set_job(job_id, "cancelled", {"error": "cancelled", "details": "cancelled by the user"})
            self._end("cancelled")
            name = self.controller.name
            task, fallback = prompts.SPAWN_JOB_CANCELLED_PROMPT.format(prompt=prompt, name=name), f'The background job "{name}" is cancelled.'
        else:
            attachments = result.get("attachments") or []
            names = "\n".join(f"- {held['name']}" for held in attachments)
            task = prompts.SPAWN_JOB_REPORT_PROMPT.format(prompt=prompt, summary=result["summary"], details=result["details"],
                                        attachments=prompts.SPAWN_JOB_ATTACHMENTS_PART.format(names=names) if attachments else "")
            fallback = f"The background job is done: {result['summary']}"
        try:
            self._report(task, fallback, attachments or None)
        except Exception as e:
            logger.error(f"job {job_id}: report failed {repr(e)}")

    def _partial_attachments(self) -> list:
        """the files a failed job made so far (Controller.delivery), [] when they can't be read"""
        try:
            return self.controller.delivery()
        except Exception as e:
            logger.error(f"job {self.job_id}: files of the failed job not found {repr(e)}")
            return []

    def _message_id(self):
        """the conversation's last user message when the job starts (it is stored before the tools run), None if not found"""
        try:
            return self.db.last_user_message_id(self.get_conversation_id())
        except Exception as e:
            logger.error(f"spawn_job: no user message for the protocol {repr(e)}")
            return None

    def _end(self, status: str, error: str = None):
        """#174 #215 the job's last protocol line, its end in the protocol (job_protocols) and in the Backroom (JobMonitor).
        it never fails the job"""
        Trace.write(self.get_conversation_id(), f"job {self.job_id} {status}", error=error, result=getattr(self.controller, "result", None))
        controller = self.controller
        try:
            controller.trace("job_finished", ok=status == "done", status=status, name=controller.name,
                             **controller.protocol.counts(controller.job_id), error=error)
            JobMonitor().finish(self.job_id, status)
        except Exception as e:
            logger.error(f"job {self.job_id}: protocol not finished {repr(e)}")
        # the "done" status stops the spinner of the workers' tool status messages, but not while a reply is being made
        # (it would end the reply's status). only to a user with an open /ws, a closed one would pile up in its queue
        turns = AgentJob.get_turns()
        if AgentJob.user_connected(self.get_user_id()) and not (turns and turns.busy(self.get_conversation_id())):
            MessageQueue().set_status("done", user_id=self.get_user_id())

    @classmethod
    def _running_in(cls, user_id: int, conversation_id: int):
        """the running job of the conversation or None. with running_lock held"""
        return next((tool for tool in cls.running.values() if tool.get_user_id() == user_id and tool.get_conversation_id() == conversation_id), None)

    @classmethod
    def add_message(cls, user_id: int, conversation_id: int, text: str) -> bool:
        """a user message of the conversation goes to its running job too, its next step gets it (Controller.add_message).
        False: no job running there"""
        with cls.running_lock:
            tool = cls._running_in(user_id, conversation_id)
            if tool is not None:
                tool.controller.add_message(text)
        return tool is not None

    def _cancel(self) -> bool:
        """the user's cancel (JobMonitor.cancel, it checked the user): stops the job. its thread saves it as cancelled, ends
        its progress and the contact reacts to it. False: it is finished"""
        with self.running_lock:
            if self.running.get(self.job_id) is not self:
                return False
            self.cancelled = True
            self.controller.trace("cancelled")
            self.controller.stop()
        logger.info(f"job {self.job_id}: cancel by user {self.get_user_id()}")
        return True

    def _progress(self, name: str, step: int, total: int):
        """the Controller's progress: planning (0 of 0) and every step i of n that starts. the planning counts as
        one part of the job, so step i of n is i / (n + 1) done"""
        JobMonitor().progress(self.job_id, name, step, total, round(100 * step / (total + 1)) if total else 0)

    def _report(self, task: str, fallback: str, attachments=None):
        """the contact tells the user what the job found, that it failed or was cancelled (task: prompts.SPAWN_JOB_REPORT_PROMPT / SPAWN_JOB_FAILED_PROMPT / SPAWN_JOB_CANCELLED_PROMPT):
        a new assistant message, stored and pushed like a companion message (AgentJob.post_message). attachments: the files
        the workers' tools held (write_file, generate_image), attached to that message, also a failed job's (unverified)"""
        contact = self.db.get_contact_by_id(self.contact_id)
        name = Utils.get_nested_value(contact, ["identity", "name"], "")
        messages = AgentJob.persona_messages(contact, self.db.get_conversation(self.get_conversation_id()), AgentJob.user_name(self.db, self.get_user_id()), task)
        text = self.controller.chat(messages, 0.7).strip() or fallback

        turns = AgentJob.get_turns()
        while turns and turns.busy(self.get_conversation_id()):
            time.sleep(1)   # a reply is being made, the report comes after it
        message_id, pushed = AgentJob.post_message(self.db, self.get_user_id(), self.get_conversation_id(), text, name)
        logger.info(f"job report sent as message {message_id}, conversation {self.get_conversation_id()}")
        JobMonitor().report(self.get_user_id(), self.job_id, message_id)    # #215 'open protocol' under it
        if attachments:
            self.tool_registry.attach_held(self.db, self.get_user_id(), self.get_conversation_id(), message_id, attachments, push=pushed)

    @classmethod
    def prompt(cls) -> str:
        return prompts.SPAWN_JOB_PROMPT
