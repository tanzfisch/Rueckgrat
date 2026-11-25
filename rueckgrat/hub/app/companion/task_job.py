import time
from datetime import datetime, timedelta

from app.agent_jobs.agent_job import AgentJob
from app.agent_jobs.job_monitor import JobMonitor
from app.agent_jobs.worker import lookup
from . import prompts
from .companion_job import short

from app.common import get_logger, Utils
logger = get_logger()

LATE_MINUTES = 5        # a one-off task this late (the hub was down) says so in its message
BUSY_WAIT_SECONDS = 120     # at most this long its message waits for a reply being made in the conversation
TITLE_LENGTH = 60           # the title of a conversation a task opens: its text, cut
TIME_LIMIT = 5400           # seconds for one pass, not an agent job's DEFAULT_TIME_LIMIT: it runs on the scheduler's thread, a long piece of work is a background job (spawn_job)
JOB_LINES = 5               # the contact's newest background jobs a pass sees (_jobs)


class TaskJob(AgentJob):
    """#170 a task of the user is due: one pass as an agent job, run by CompanionScheduler on its thread like a CompanionJob.
    it does the task: a Worker loop on the task looks up or does what it needs (lookup, it may start a background job),
    then one call in the contact's persona with what it found makes the message. it is posted in the conversation the task
    was asked in (a new one if that was deleted), whatever the companion's chattiness and quiet hours; with the task's
    alarm the app rings. a task that only reports a change and found none stays silent (prompts.TASK_SILENT). the pass
    sees the real state of the contact's background jobs (_jobs): a task that checks one reads it there"""
    # its lookup's tools besides the detected ones: what the user told the contact before
    ALWAYS_TOOLS = ("search_memory",)
    ALLOWED_TOOLS = ("spawn_job", "poll", "show_map")    # its message shows the poll or map (ToolRegistry.show_held)
    EXCLUDED_TOOLS = ("take_photo",)

    def __init__(self, row: dict, db, infrastructure, tool_registry, tz, now: datetime, occurrence: datetime):
        super().__init__("task", row["note"], time_limit=TIME_LIMIT, infrastructure=infrastructure)
        self.row = row
        self.user_id = row["user_id"]
        self.db = db
        self.tool_registry = tool_registry
        self.tz = tz
        self.now = now
        self.occurrence = occurrence
        self.outcome = None
        self.log = {}   # like CompanionJob.log, kept in companion_log by the scheduler

    def step(self) -> bool:
        try:
            self.outcome = self.result = self._pass()
        except Exception as e:
            self.log["error"] = short(repr(e), 300)
            raise
        return True

    def late(self) -> bool:
        """a one-off task that could not run at its time"""
        return not self.row["recurrence"] and self.now - self.occurrence > timedelta(minutes=LATE_MINUTES)

    def _pass(self) -> dict:
        row, user_id, contact_id = self.row, self.row["user_id"], self.row["contact_id"]
        local = self.now.astimezone(self.tz)
        contact = self.db.get_contact_by_id(contact_id)
        name = Utils.get_nested_value(contact, ["identity", "name"], "")
        user_name = self.user_name(self.db, user_id)
        conversation = self._conversation(user_id, contact_id)
        self.tool_context = {"tool_registry": self.tool_registry, "db": self.db, "user_id": user_id, "contact_id": contact_id,
                             "conversation_id": conversation["id"], "user_name": user_name}
        due = self.occurrence.astimezone(self.tz)
        due_time = due.strftime("%H:%M" if due.date() == local.date() else "%a %d %b %H:%M")
        values = {
            "name": name,
            "user_name": user_name,
            "task": row["note"],
            "due_time": due_time,
            "local_time": local.strftime("%Y-%m-%d %H:%M"),
            "weekday": local.strftime("%A"),
            "timezone": str(self.tz),
            "late": prompts.TASK_LATE_PART.format(due_time=due_time) if self.late() else "",
            "jobs": self._jobs(user_id, contact_id),
        }
        if self.late():
            self.log["late"] = f"was due at {due_time}"
        found = self._lookup(row["note"] + values["jobs"]) if self.tool_registry else ""
        messages = self.persona_messages(contact, conversation, user_name, prompts.user_task_prompt(values, found))
        text = self.chat(messages, 0.7).strip()
        if text.strip(" .\"'").upper() == prompts.TASK_SILENT:
            self.log["message"] = "silent: nothing to tell"
            logger.info(f"task {row['id']} contact {contact_id}: nothing to tell")
            return {"result": "nothing to tell", "message_id": None}
        if not text:
            self.log["error"] = "no answer from the model"
            text = f"⏰ {row['note']}"     # the user asked for it: the task text at least
        text = text[:4000]

        self._wait_for_reply(conversation["id"])
        message_id, pushed = self.post_message(self.db, user_id, conversation["id"], text, name, alarm=bool(row["alarm"]))
        if self.attachments:
            self.tool_registry.attach_held(self.db, user_id, conversation["id"], message_id, self.attachments, push=pushed)
        if self.held_data:
            self.tool_registry.show_held(self.db, user_id, conversation["id"], message_id, self.held_data, push=pushed)
        self.log["message"] = f"sent #{message_id}{', alarm' if row['alarm'] else ''}, {'pushed' if pushed else 'stored (user not connected)'}: {short(text)!r}"
        logger.info(f"task {row['id']} contact {contact_id}: message {message_id}, conversation {conversation['id']}")
        return {"result": short(text, 2000), "message_id": message_id}

    def _jobs(self, user_id: int, contact_id: int) -> str:
        """the contact's JOB_LINES newest background jobs of the last day with their state (JobMonitor.snapshot) as
        prompts.TASK_JOBS_PART, "" without any"""
        items = [item for item in JobMonitor().snapshot(user_id) if item["kind"] == "job" and item["contact_id"] == contact_id]
        lines = [prompts.TASK_JOB_LINE.format(
            name=item["name"], state=item["state"], started=self._local(item["started_at"]),
            finished=prompts.TASK_JOB_FINISHED_PART.format(finished=self._local(item["finished_at"])) if item["finished_at"] else "")
            for item in items[:JOB_LINES]]
        return prompts.TASK_JOBS_PART.format(jobs="\n".join(lines)) if lines else ""

    def _local(self, stamp: str) -> str:
        """a job's utc time (job_monitor.utc_now) as the user's local time"""
        return datetime.fromisoformat(stamp).astimezone(self.tz).strftime("%a %H:%M")

    def _conversation(self, user_id: int, contact_id: int) -> dict:
        """the conversation the task was asked in, read now (an earlier task of this tick may have opened one). deleted
        (or there was none): a new one, the contact's other tasks without a conversation post there too"""
        current = self.db.get_tasks(user_id, task_id=self.row["id"])
        conversation_id = current[0]["conversation_id"] if current else self.row.get("conversation_id")
        conversation = self.db.get_conversation(conversation_id) if conversation_id else None
        if conversation:
            return conversation
        conversation_id = self.db.create_conversation(user_id, contact_id)
        self.db.update_conversation(conversation_id, short(f"⏰ {self.row['note']}", TITLE_LENGTH), "")    # not "..." in the list
        self.db.adopt_tasks(contact_id, conversation_id)
        self.log["conversation"] = f"new #{conversation_id}: the task's conversation was deleted or there was none"
        return self.db.get_conversation(conversation_id)

    def _lookup(self, task: str) -> str:
        """what the task's lookup (worker.lookup) found, a failed one says so: the message does not claim it worked.
        the files and data it holds (the price ranking) go with the message"""
        found, worker = lookup(self, task, self.ALWAYS_TOOLS, self.ALLOWED_TOOLS, self.EXCLUDED_TOOLS)
        self.log["lookup"] = f"{', '.join(worker.called()) or 'no tools'} in {worker.calls} calls -> {short(found)}"
        return found

    def _wait_for_reply(self, conversation_id: int):
        """a reply being made in the conversation comes first, the task's message after it (not longer than BUSY_WAIT_SECONDS)"""
        turns = self.get_turns()
        deadline = time.monotonic() + BUSY_WAIT_SECONDS
        while turns and turns.busy(conversation_id) and time.monotonic() < deadline:
            time.sleep(1)
