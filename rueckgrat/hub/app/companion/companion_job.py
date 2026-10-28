import json
import random
from datetime import datetime, timedelta, timezone

from app.jobs.job_queue import Job
from app.utils.prompt_compiler import PromptCompiler
from . import prompts
from .clock import to_db, from_db, local_day, at_local, parse_hhmm

from app.common import get_logger, Utils, MessageQueue
logger = get_logger()

# the lookups a pass may do, one per pass at most
ALLOWED_TOOLS = ["search_memory", "websearch", "wikipedia", "weather"]

# guardrails, enforced here whatever the model answers
MAX_MESSAGES_PER_DAY = 3
MIN_HOURS_BETWEEN_MESSAGES = 2
USER_ACTIVE_MINUTES = 30        # the user wrote that recently: they are chatting, don't interrupt
QUIET_HOURS = (22, 8)           # local hours [from, to) without proactive messages
MAX_ROWS_PER_PASS = 5
MAX_PENDING_ROWS = 12           # one-off rows waiting per companion
ROW_KINDS = ("event", "check_in", "news", "reflection")   # what a pass may put on the calendar, all one-off
SILENT_KINDS = ("planning",)

def may_message(local: datetime, user_minutes: float | None, sent_today: int, sent_recently: bool) -> tuple[bool, str]:
    """the guardrails of a proactive message: (allowed, reason)"""
    quiet_from, quiet_to = QUIET_HOURS
    if local.hour >= quiet_from or local.hour < quiet_to:
        return False, "quiet hours"
    if sent_today >= MAX_MESSAGES_PER_DAY:
        return False, "daily limit reached"
    if sent_recently:
        return False, f"sent one less than {MIN_HOURS_BETWEEN_MESSAGES}h ago"
    if user_minutes is not None and user_minutes < USER_ACTIVE_MINUTES:
        return False, "user is chatting"
    return True, "ok"

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

class CompanionJob(Job):
    """one pass of a companion: a calendar row fired. one decision call, at most one lookup and one more call,
    then the answer is applied: calendar rows, maybe a message. the scheduler re-arms or closes the row"""

    def __init__(self, row: dict, db, infrastructure, tool_registry, tz, now: datetime, turns=None, is_connected=None):
        super().__init__()
        self.row = row
        self.db = db
        self.infrastructure = infrastructure
        self.tool_registry = tool_registry
        self.tz = tz
        self.now = now
        self.turns = turns
        self.is_connected = is_connected or (lambda user_id: False)
        self.tool_calls = 0
        self.outcome = None
        self.log = {}   # what this pass decided, short texts. the scheduler keeps it in companion_log (hub management)

    def execute(self) -> None:
        try:
            self.outcome = self._pass()
        except Exception as e:
            self.log["error"] = short(repr(e), 300)
            raise

    def result(self):
        return self.outcome

    def _pass(self) -> dict:
        row, kind = self.row, self.row["kind"]
        user_id, contact_id = row["user_id"], row["contact_id"]
        local = self.now.astimezone(self.tz)

        contact = self.db.get_contact_by_id(contact_id)
        name = Utils.get_nested_value(contact, ["identity", "name"], "")
        user_name = self._user_name(user_id)
        conversation = self._conversation(user_id, contact_id)
        day_start, day_end = local_day(local)

        last_user = self.db.last_user_message_time(contact_id)
        user_minutes = (self.now - from_db(last_user)).total_seconds() / 60 if last_user else None
        sent_today = self.db.count_companion_messages(contact_id, day_start)
        context = conversation.get("context") if isinstance(conversation.get("context"), dict) else {}

        values = {
            "name": name,
            "user_name": user_name,
            "local_time": local.strftime("%Y-%m-%d %H:%M"),
            "weekday": local.strftime("%A"),
            "timezone": str(self.tz),
            "since_user": since_text(user_minutes),
            "sent_today": sent_today,
            "max_per_day": MAX_MESSAGES_PER_DAY,
            "calendar": self._calendar_text(contact_id, day_start, day_end) or "nothing yet",
            "last_reflection": self.db.last_companion_result(contact_id, "reflection") or "none",
            "messages": self._messages_text(conversation["id"]) or "none",
            "summary": context.get("summary") or "none",
            "note": row.get("note") or "",
        }
        if kind == "planning":
            self.log["reflection"] = short(values["last_reflection"])
        tools = self._tools_offer()
        system_prompt, _ = PromptCompiler(contact=contact, conversation=conversation, user_role_name=user_name).build_prompt()
        messages = [
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": prompts.task_prompt(kind, values, tools)},
        ]
        logger.info(f"companion pass {kind} contact {contact_id} prompt v{prompts.PROMPT_VERSION}")

        reply = self._ask(messages)
        tool_call = (reply or {}).get("tool_call")
        if tools and isinstance(tool_call, dict) and tool_call.get("tool") in ALLOWED_TOOLS:
            self.tool_calls += 1
            found = self._lookup(tool_call, user_id, contact_id, conversation["id"])
            query = {k: v for k, v in tool_call.items() if k != "tool"}
            self.log["lookup"] = f"{tool_call['tool']} {short(json.dumps(query, ensure_ascii=False), 150)} -> {len(found)} chars"
            messages.append({"role": "assistant", "content": json.dumps({"tool_call": tool_call})})
            messages.append({"role": "user", "content": prompts.lookup_result_prompt(found)})
            reply = self._ask(messages)   # the final answer, a second tool call in it is ignored
        elif isinstance(tool_call, dict):
            self.log["lookup"] = f"{short(tool_call.get('tool'), 40)} not allowed, ignored"
        if reply is None:
            self.log["error"] = "no usable answer from the model"
        reply = reply or {}

        added = self._add_calendar(reply.get("calendar"), contact_id)

        message_id, reason = None, "silent pass"
        if kind not in SILENT_KINDS:
            sent_recently = self.db.count_companion_messages(contact_id, to_db(self.now - timedelta(hours=MIN_HOURS_BETWEEN_MESSAGES))) > 0
            message_id, reason = self._maybe_message(reply.get("message"), user_id, conversation["id"], name, local, user_minutes, sent_today, sent_recently)

        result = str(reply.get("thoughts") or "").strip()[:2000]
        self.log["thoughts"] = short(result)
        self.log.setdefault("message", f"quiet: {reason}" if not message_id else "sent")
        logger.info(f"companion pass {kind} contact {contact_id}: {len(added)} rows, message {message_id} ({reason})")
        return {"result": result, "message_id": message_id, "reason": reason, "added": added}

    def _ask(self, messages: list) -> dict | None:
        content = self.infrastructure.chat(messages=messages, temperature=0.7, seed=random.randint(0, 100000))
        data = Utils.json_loads(content) if content else None
        return data if isinstance(data, dict) else None

    def _user_name(self, user_id: int) -> str:
        user_data = self.db.get_user_data(user_id) or {}
        try:
            name = json.loads(user_data.get("profile") or "{}").get("name")
        except Exception:
            name = None
        return name or "the user"

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

    def _tools_offer(self) -> str:
        tools = self.tool_registry.tools
        return "\n".join(f"- {tools[n].name()}: {tools[n].get_description()}\n  {tools[n].example()}" for n in ALLOWED_TOOLS if n in tools)

    def _lookup(self, tool_call: dict, user_id: int, contact_id: int, conversation_id: int) -> str:
        response = {}
        self.tool_registry.execute(user_id=user_id, contact_id=contact_id, conversation_id=conversation_id,
                                   response=response, tool_calls=[tool_call], parallel=False)
        lines = [f"{r.get('title', '')} - {r.get('answer', '')} - source {r.get('source', '')}" for r in response.get("websearch_results", [])]
        lines += [f"{r.get('tool')}: {r.get('text') or 'failed - ' + str(r.get('error'))}" for r in response.get("tool_results", [])]
        return "\n".join(lines) or "nothing found"

    def _add_calendar(self, items, contact_id: int) -> list[int]:
        """valid new rows only: ROW_KINDS, later today or tomorrow (max 36h ahead), no duplicates, capped"""
        added, plan = [], []
        local = self.now.astimezone(self.tz)
        for item in (items if isinstance(items, list) else [])[:MAX_ROWS_PER_PASS]:
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
        if self.db.count_pending_companion_rows(contact_id) >= MAX_PENDING_ROWS:
            return "calendar full"
        note = " ".join(str(item.get("note") or "").split())[:200]
        if self.db.has_companion_row(contact_id, to_db(due), item["kind"], note):
            return "duplicate"
        added.append(self.db.add_companion_row(contact_id, to_db(due), item["kind"], note))
        return None

    def _maybe_message(self, message, user_id: int, conversation_id: int, name: str, local: datetime,
                       user_minutes: float | None, sent_today: int, sent_recently: bool) -> tuple[int | None, str]:
        """stores the message like a normal reply and pushes it when the user is connected"""
        if not isinstance(message, dict):
            return None, "no message decision"
        if message.get("send") is not True:
            return None, f"model: {str(message.get('reason', ''))[:200]}"
        text = str(message.get("text") or "").strip()[:1000]
        if not text:
            return None, "empty text"
        allowed, reason = may_message(local, user_minutes, sent_today, sent_recently)
        if allowed and self.turns and self.turns.busy(conversation_id):
            allowed, reason = False, "a reply is being made"
        if allowed and not self.db.is_companion(self.row["contact_id"]):
            allowed, reason = False, "switched off during the pass"
        if not allowed:
            self.log["message"] = f"quiet: {reason}, wanted to say {short(text)!r}"
            return None, reason

        message_id = self.db.add_message(conversation_id, "assistant", text, name)
        pushed = self.is_connected(user_id)
        self.log["message"] = f"sent #{message_id}, {'pushed' if pushed else 'stored (user not connected)'}: {short(text)!r}"
        if pushed:
            MessageQueue().send_data({"chat": {
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": text,
                "tool_calls": [],
                "message_id": message_id
            }})
        return message_id, "sent"
