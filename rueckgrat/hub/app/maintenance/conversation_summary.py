import random
import re
from datetime import datetime, timezone

from app.jobs.job_queue import Job
from app.utils.embeddings import embed_text
from app.companion.clock import to_db
from .sweeper import MaintenanceTask

from app.common import get_logger
logger = get_logger()

MAX_MESSAGES = 60           # the latest messages a summary is made from, older ones live on in the previous summary
MAX_MESSAGE_CHARS = 500
MAX_WORDS = 120             # bge-small reads 512 tokens, a longer summary would be cut for the vector

class ConversationSummaryTask(MaintenanceTask):
    """a summary and its vector per conversation, for finding old conversations by meaning (search_memory).
    pending: no summary yet (the backfill), messages newer than the summary, or no vector (the embedding node was away)"""
    name = "summaries"

    def __init__(self, db, infrastructure):
        self.db = db
        self.infrastructure = infrastructure

    def pending(self, user_id, limit):
        return self.db.conversations_to_summarize(user_id, limit)

    def job(self, item):
        return ConversationSummaryJob(item, self.db, self.infrastructure)

    def status(self):
        return self.db.summary_status()

class ConversationSummaryJob(Job):
    """(re)makes the summary of one conversation if it is stale, then embeds it. result() is a short outcome"""

    def __init__(self, item: dict, db, infrastructure):
        super().__init__()
        self.item = item
        self.db = db
        self.infrastructure = infrastructure
        self.outcome = "not run"

    def execute(self) -> None:
        try:
            self.outcome = self._run()
        except Exception as e:
            self.outcome = f"failed {repr(e)}"
            raise

    def result(self) -> str:
        return f"conversation {self.item['id']}: {self.outcome}"

    def _run(self) -> str:
        conversation_id, summary = self.item["id"], self.item["summary"]
        if self.item["stale"]:
            started = to_db(datetime.now(timezone.utc))   # before reading: a message arriving meanwhile makes it stale again
            summary = self._summarize(summary)
            if not summary:
                return "no summary from the model, next night again"
            self.db.set_conversation_summary(conversation_id, summary, started)
        vector = embed_text(self.infrastructure, summary)
        if vector is None or not self.db.set_conversation_embedding(conversation_id, vector):
            return "summary stored, no vector (embedding node?)"
        return "summarized and embedded" if self.item["stale"] else "embedded"

    def _summarize(self, previous: str | None) -> str | None:
        messages = self.db.get_messages_by_conversation(self.item["id"], MAX_MESSAGES) or []
        lines = []
        for m in messages:
            if m["role"] not in ("user", "assistant"):
                continue
            text = " ".join(re.sub(r"```.*?```", "[code]", m["content"], flags=re.DOTALL).split())
            lines.append(f"- {m['role']}: {text[:MAX_MESSAGE_CHARS]}")
        if not lines:
            return None

        earlier = f"EARLIER SUMMARY (of this conversation, may be out of date):\n{previous}\n\n" if previous else ""
        query = f"""{earlier}MESSAGES:
{chr(10).join(lines)}

Summarize the whole conversation in at most {MAX_WORDS} words, so it can be found again later by its content.
Name the topics, people, places, plans, decisions and facts the user shared. Keep what still matters from the earlier summary.
Plain text, no lists, no preface. Reply with the summary only."""
        content = self.infrastructure.chat(
            messages=[
                {"role": "system", "content": "You write short, factual summaries of chat conversations. Use only the given text."},
                {"role": "user", "content": query},
            ],
            temperature=0.2,
            seed=random.randint(0, 100000),
            max_new_tokens=300,
        )
        return content.strip()[:2000] if content and content.strip() else None
