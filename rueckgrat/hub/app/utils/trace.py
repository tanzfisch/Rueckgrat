import os
import json
import threading
from datetime import datetime
from typing import Any, Optional

from app.common import get_logger
logger = get_logger()

TRACE_ENV = "RUECKGRAT_TRACE"       # 1 / true / on: every decision of a turn or a job is written to the trace files
TRACE_DIR = "/hub/logs/trace"       # compose mounts ./logs, one file per conversation


class Trace:
    """the decision trace: what each llm call and tool detection was asked, what it answered and what came of it
    (tool scores, setup prompts and raw replies, parsed and dropped calls, tool results, the workers' and the
    controller's calls). off unless RUECKGRAT_TRACE is set, written to TRACE_DIR/conversation_<id>.log, never raises"""
    _lock = threading.Lock()
    _warned = False     # a folder the hub can't write to is logged once, not on every entry

    @staticmethod
    def enabled() -> bool:
        return os.environ.get(TRACE_ENV, "").strip().lower() in ("1", "true", "yes", "on")

    @classmethod
    def write(cls, conversation_id: Optional[int], event: str, text: str = "", **data: Any) -> None:
        """one entry: a header line with the time, the thread, event and data (json), then text as it is"""
        if not cls.enabled():
            return
        try:
            name = f"conversation_{conversation_id}.log" if conversation_id is not None else "hub.log"
            header = f"===== {datetime.now().astimezone().isoformat(timespec='milliseconds')} [{threading.current_thread().name}] {event}"
            if data:
                header += " " + json.dumps(data, ensure_ascii=False, default=str)
            entry = header + "\n" + (f"{text}\n" if text else "") + "\n"
            with cls._lock:
                os.makedirs(TRACE_DIR, exist_ok=True)
                with open(os.path.join(TRACE_DIR, name), "a", encoding="utf-8") as file:
                    file.write(entry)
        except Exception as e:
            if not cls._warned:
                cls._warned = True
                logger.warning(f"trace not written to {TRACE_DIR} {repr(e)} (it has to be writable for the hub's user, uid 1000)")

    @staticmethod
    def messages(messages: list) -> str:
        """llm messages as text, each under its role"""
        return "\n".join(f"----- {m.get('role')} -----\n{m.get('content')}" for m in messages or [])
