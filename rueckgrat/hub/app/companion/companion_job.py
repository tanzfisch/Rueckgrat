from datetime import datetime, timedelta

from app.agent_jobs.agent_job import AgentJob
from app.agent_jobs.worker import lookup
from . import prompts
from .outreach import Outreach
from .settings import CompanionSettings
from app.utils.clock import to_db, from_db, local_day, at_local, parse_hhmm

from app.common import get_logger, Utils
logger = get_logger()

# the tools a pass's lookup always has, besides the detected ones: what the user told it before and a photo (when the
# settings allow photos). of this kind too: laya's websearch questions are about chat messages, a news scan needs its websearch
ALWAYS_TOOLS = ("search_memory", "take_photo")
KIND_TOOLS = {"news": ("websearch",)}

# the guardrails (message limits, quiet hours, rows per pass) come from the contact's settings: CompanionSettings
ROW_KINDS = ("event", "check_in", "news", "reflection")   # what a pass may put on the calendar, all one-off
SILENT_KINDS = ("planning",)
TIME_LIMIT = 5400   # seconds for one pass, not an agent job's DEFAULT_TIME_LIMIT: it runs on the scheduler's thread

def short(text, n: int = 200) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 3] + "..."

def since_text(minutes: float | None) -> str:
    if minutes is None:
        return "never"
    if minutes < 90:
        return f"{int(minutes)} minutes ago"
    if minutes < 48 * 60:
        return f"{int(minutes // 60)} hours ago"
    return f"{int(minutes // (24 * 60))} days ago"

class CompanionJob(AgentJob):
    """one pass of a companion as an agent job: a calendar row fired. its one step: a Worker loop looks up what the pass
    needs (lookup), one decision call with what it found, then the answer is applied: calendar rows, maybe a message.
    the scheduler runs it on its own thread (run()) and re-arms or closes the row"""
    # it may take a photo and offer files of the contact's sandbox files (sent with its message), not make pictures, audio
    # or files: those are for jobs the user asked for. nor reset the sandbox: no one asked for it
    EXCLUDED_TOOLS = ("generate_image", "write_file", "edit_file", "text_to_speech", "join_files", "reset_sandbox")
    ALLOWED_TOOLS = ("poll", "show_map")     # its message shows the poll or map (ToolRegistry.show_held)

    def __init__(self, row: dict, db, infrastructure, tool_registry, tz, now: datetime):
        super().__init__("companion", row["kind"], time_limit=TIME_LIMIT, infrastructure=infrastructure)
        self.row = row
        self.user_id = row["user_id"]   # status messages of its tool lookups and the push go to the contact's owner only
        self.db = db
        self.tool_registry = tool_registry
        self.tz = tz
        self.now = now
        self.outcome = None
        self.settings = None    # CompanionSettings of the contact, read at the start of the pass
        self.log = {}   # what this pass decided, short texts. the scheduler keeps it in companion_log (hub management)

    def step(self) -> bool:
        try:
            self.outcome = self.result = self._pass()
        except Exception as e:
            self.log["error"] = short(repr(e), 300)
            raise
        return True

    def _pass(self) -> dict:
        row, kind = self.row, self.row["kind"]
        user_id, contact_id = row["user_id"], row["contact_id"]
        local = self.now.astimezone(self.tz)

        contact = self.db.get_contact_by_id(contact_id)
        self.settings = CompanionSettings(contact)
        name = Utils.get_nested_value(contact, ["identity", "name"], "")
        user_name = self.user_name(self.db, user_id)
        conversation = self._conversation(user_id, contact_id)
        self.tool_context = {"tool_registry": self.tool_registry, "db": self.db, "user_id": user_id, "contact_id": contact_id,
                             "conversation_id": conversation["id"], "user_name": user_name}
        day_start, day_end = local_day(local)

        last_user = self.db.last_user_message_time(contact_id)
        user_minutes = (self.now - from_db(last_user)).total_seconds() / 60 if last_user else None
        sent_today = self.db.count_companion_messages(contact_id, day_start)

        values = {
            "name": name,
            "user_name": user_name,
            "local_time": local.strftime("%Y-%m-%d %H:%M"),
            "weekday": local.strftime("%A"),
            "timezone": str(self.tz),
            "since_user": since_text(user_minutes),
            "sent_today": sent_today,
            "calendar": self._calendar_text(contact_id, day_start, day_end) or "nothing yet",
            "last_reflection": self.db.last_companion_result(contact_id, "reflection") or "none",
            "messages": self._messages_text(conversation["id"]) or "none",
            "summary": conversation.get("summary") or "none",
            "note": row.get("note") or "",
            **self.settings.prompt_values(),
        }
        if kind == "planning":
            self.log["reflection"] = short(values["last_reflection"])
        found = self._lookup(kind, values) if self.tool_registry else ""
        messages = self.persona_messages(contact, conversation, user_name, prompts.task_prompt(kind, values, found))
        logger.info(f"companion pass {kind} contact {contact_id} prompt v{prompts.PROMPT_VERSION}")

        reply = self._ask(messages)
        if reply is None:
            self.log["error"] = "no usable answer from the model"
        reply = reply or {}

        added = self._add_calendar(reply.get("calendar"), contact_id)

        message_id, reason = None, "silent pass"
        if kind not in SILENT_KINDS:
            sent_recently = self.db.count_companion_messages(contact_id, to_db(self.now - timedelta(hours=self.settings.chattiness.min_hours))) > 0
            message_id, reason = self._maybe_message(reply.get("message"), user_id, conversation["id"], name, local, user_minutes, sent_today, sent_recently)

        result = str(reply.get("thoughts") or "").strip()[:2000]
        self.log["thoughts"] = short(result)
        self.log.setdefault("message", f"quiet: {reason}" if not message_id else "sent")
        logger.info(f"companion pass {kind} contact {contact_id}: {len(added)} rows, message {message_id} ({reason})")
        return {"result": result, "message_id": message_id, "reason": reason, "added": added}

    def _ask(self, messages: list) -> dict | None:
        content = self.chat(messages, 0.7)
        data = Utils.json_loads(content) if content else None
        return data if isinstance(data, dict) else None

    def _conversation(self, user_id: int, contact_id: int) -> dict:
        """the latest conversation with the contact, a new one if there is none"""
        conversations = self.db.get_conversations(user_id, contact_id)
        if conversations:
            return self.db.get_conversation(conversations[0]["id"])
        return self.db.get_conversation(self.db.create_conversation(user_id, contact_id))

    def _messages_text(self, conversation_id: int) -> str:
        messages = self.db.get_messages_by_conversation(conversation_id, 10) or []
        return "\n".join(f'- {m["role"]}: {" ".join(m["content"].split())[:300]}' for m in messages)

    def _calendar_text(self, contact_id: int, start: str, end: str) -> str:
        lines = []
        for r in self.db.get_companion_day(contact_id, start, end):
            fired_today = r["fired_at"] and start <= r["fired_at"] < end
            at = from_db(r["fired_at"] if fired_today else r["due_at"]).astimezone(self.tz).strftime("%H:%M")
            note = f" - {r['note']}" if r["note"] else ""
            outcome = f" ({r['result'][:300]})" if fired_today and r["result"] else ("" if fired_today else " (planned)")
            lines.append(f"{at} {r['kind']}{note}{outcome}")
        return "\n".join(lines)

    def _lookup(self, kind: str, values: dict) -> str:
        """what the pass's lookup (worker.lookup on its intent: no jobs, images or memory writes) found, "" when it
        failed. a photo it took or files it offered are attached when it sends its message (_maybe_message)"""
        found, worker = lookup(self, prompts.intent(kind, values), ALWAYS_TOOLS + KIND_TOOLS.get(kind, ()), self.ALLOWED_TOOLS,
                               self.EXCLUDED_TOOLS + self.settings.excluded_tools, failed=False)
        if worker.calls:
            self.log["lookup"] = f"{', '.join(worker.called()) or 'no tools'} in {worker.calls} calls -> {short(found)}"
        return found

    def _add_calendar(self, items, contact_id: int) -> list[int]:
        """valid new rows only: ROW_KINDS, later today or tomorrow (max 36h ahead), no duplicates, capped by the settings"""
        added, plan = [], []
        local = self.now.astimezone(self.tz)
        for item in (items if isinstance(items, list) else [])[:self.settings.chattiness.max_rows]:
            if not isinstance(item, dict):
                continue
            entry = f"{short(item.get('kind'), 20)} {short(item.get('day'), 10)} {short(item.get('time'), 10)} {short(item.get('note'), 80)!r}"
            skipped = self._add_row(item, contact_id, local, added)
            plan.append(f"{entry}: {skipped or 'added'}")
            if skipped == "calendar full":
                logger.warning(f"companion {contact_id}: calendar full")
                break
        self.log["plan"] = plan   # [] = an empty plan
        return added

    def _add_row(self, item: dict, contact_id: int, local: datetime, added: list) -> str | None:
        """adds one planned row, else returns why not"""
        if item.get("kind") not in ROW_KINDS:
            return "unknown kind"
        at = parse_hhmm(item.get("time"))
        if not at:
            return "bad time"
        day = local.date() + timedelta(days=1 if item.get("day") == "tomorrow" else 0)
        due = at_local(day, at, self.tz)
        if not self.now < due <= self.now + timedelta(hours=36):
            return "not later today or tomorrow"
        if self.db.count_pending_companion_rows(contact_id) >= self.settings.chattiness.max_pending:
            return "calendar full"
        note = " ".join(str(item.get("note") or "").split())[:200]
        if self.db.has_companion_row(contact_id, to_db(due), item["kind"], note):
            return "duplicate"
        added.append(self.db.add_companion_row(contact_id, to_db(due), item["kind"], note))
        return None

    def _maybe_message(self, message, user_id: int, conversation_id: int, name: str, local: datetime,
                       user_minutes: float | None, sent_today: int, sent_recently: bool) -> tuple[int | None, str]:
        """holds both versions of the message (#167) until the user opens the contact or the window passes"""
        if not isinstance(message, dict):
            return None, "no message decision"
        if message.get("send") is not True:
            return None, f"model: {str(message.get('reason', ''))[:200]}"
        reach_out = str(message.get("reach_out") or message.get("text") or "").strip()[:1000]
        surprise = str(message.get("surprise") or "").strip()[:1000]
        if not surprise:
            surprise = reach_out
        if not reach_out:
            reach_out = surprise
        if not reach_out:
            return None, "empty text"
        allowed, reason = self.settings.may_message(local, user_minutes, sent_today, sent_recently)
        turns = self.get_turns()
        if allowed and turns and turns.busy(conversation_id):
            allowed, reason = False, "a reply is being made"
        if allowed and not self.db.is_companion(self.row["contact_id"]):
            allowed, reason = False, "switched off during the pass"
        if not allowed:
            self.log["message"] = f"quiet: {reason}, wanted to say {short(reach_out)!r}"
            return None, reason

        # #167 hold both versions; they are posted when the user opens the contact or the window passes
        message_id, reason = Outreach().hold(
            user_id, self.row["contact_id"], conversation_id, name, surprise, reach_out,
            self.settings.reach_window, now=self.now, source_id=self.row["id"], job_id=self.job_id,
            attachments=self.attachments or None, held_data=self.held_data or None)
        if message_id:
            self.log["message"] = f"sent #{message_id} (surprise, contact was open): {short(surprise)!r}"
            return message_id, "sent"
        self.log["message"] = (f"held until {self.now + self.settings.reach_window:%Y-%m-%d %H:%M} UTC: "
                               f"surprise {short(surprise)!r}, reach_out {short(reach_out)!r}")
        return None, reason
