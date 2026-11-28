"""
laya_tune's stack mode: each dataset row goes through MetaTask's tool detection and ToolExecutionTask's
setup rounds. Laya and the LLM are the live nodes (HTTP); the tools are recorded and not executed.
"""
import json
import logging
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.common import ChatRequest
from app.tasks.meta_task import MetaTask
from app.tasks.task_queue import TaskQueue
from app.tools.tool_registry import ToolRegistry
from app.utils.infrastructure import Infrastructure

from app.tools.map_tool import MapTool
from app.utils.message_shape import MessageShape

from .lever_advisor import LeverAdvisor
from .progress import Progress, short_label
from .tune_db import TuneDb

LAYA = os.environ.get("LAYA_DECIDE", "192.168.2.158:7346")
LLM = os.environ.get("LLM_CHAT", "192.168.2.39:7346")
IMAGE = os.environ.get("IMAGE_NODE", "192.168.2.239:7346")
TTS = os.environ.get("TTS_NODE", LAYA)    # the laya node also serves tts when no TTS_NODE is set

# a short earlier exchange so the pick and the setup see a normal chat, not an empty conversation.
# a plain hello, not an offer to help: a self-contained new task must not look like a follow-up to "how can I help you"
NEUTRAL_HISTORY = (
    {"role": "user", "content": "Hello."},
    {"role": "assistant", "content": "Hello."},
)


def _node(spec: str) -> SimpleNamespace:
    host, port = spec.rsplit(":", 1)
    return SimpleNamespace(addr=host, port=int(port))


def _config_path() -> Optional[Path]:
    here = Path(__file__).resolve()
    candidates = (
        Path("/hub/config/infrastructure.json"),
        here.parents[2] / "config" / "infrastructure.json",
    )
    return next((path for path in candidates if path.exists()), None)


def stack_infrastructure() -> Infrastructure:
    """decide and chat over HTTP, no websocket and no config watch. nodes come from infrastructure.json when
    it is there, else LAYA_DECIDE / LLM_CHAT / IMAGE_NODE / TTS_NODE"""
    nodes = {}
    path = _config_path()
    if path is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
        for host in data.get("hosts") or []:
            node = host.get("node") or {}
            client = SimpleNamespace(addr=host["addr"], port=int(node["port"]))
            for entry in (node.get("services") or []) + (node.get("modules") or []):
                if entry.get("type"):
                    nodes[entry["type"]] = client
    defaults = {
        "text_to_decision": _node(LAYA),
        "text_to_text": _node(LLM),
        "text_to_image": _node(IMAGE),
        "text_to_speech": _node(TTS),
    }
    for name, node in defaults.items():
        nodes.setdefault(name, node)

    infrastructure = Infrastructure.__new__(Infrastructure)
    infrastructure._live = False
    infrastructure._simulated_offline = False
    infrastructure.internet = True
    infrastructure._nomad = None
    infrastructure._settings = None
    infrastructure.node_by_type = nodes
    return infrastructure


def prior_messages(text: str, followup: str = "") -> List[Dict[str, str]]:
    """a short earlier exchange for a follow-up row when the phrase has a clear antecedent, else a neutral chat.
    dataset rows use NEUTRAL_HISTORY (pass followup='')."""
    low = " ".join(text.lower().split())
    if not followup:
        return list(NEUTRAL_HISTORY)

    def pair(user: str, assistant: str) -> List[Dict[str, str]]:
        return [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]

    if any(word in low for word in ("that one", "the first one", "the second one", "the other one")):
        return pair("Which of these should I use, the first one or the second one?",
                    "I can use either. The first one is shorter, the second one has more detail.")
    if "other file" in low or "the file is ready" in low or "when it's done" in low or "when its done" in low:
        return pair("Please write a short report and save it as a file.",
                    "I can write the report and save it. Tell me if you want me to start.")
    if "the numbers" in low:
        return pair("Can you add up the figures in the last invoice?",
                    "Yes. I can add them when I have the numbers.")
    if "berlin" in low and "same" in low:
        return pair("What's the weather in Paris today?",
                    "In Paris it is mild and cloudy, around 14 degrees.")
    if "tests for it" in low or "test cases" in low or "tune it" in low:
        return pair("Please look at the tuner and tell me how it decides the thresholds.",
                    "It scores each labelled example and picks the threshold pair with the most correct rows.")
    if "on a map" in low:
        return pair("Where is the Eiffel Tower?",
                    "The Eiffel Tower is in Paris. I can show it on a map if you like.")
    if "start it" in low or "do that" in low or "the same again" in low:
        return pair("Could you start a small background job to build a fizzbuzz project with tests?",
                    "Yes, I can start that job whenever you want.")
    if "stop" in low or "working on anything" in low:
        return pair("Please start a background job to build a fizzbuzz project with tests.",
                    "I have started the job. I will tell you when it is done.")
    return list(NEUTRAL_HISTORY)


def _request(text: str, db: TuneDb) -> ChatRequest:
    return ChatRequest(
        contact_id=db.contact_id,
        conversation_id=db.conversation_id,
        role="user",
        name="user",
        content=text,
        temperature=0.0,
    )


def _meta(text: str, db: TuneDb, registry: ToolRegistry, infrastructure: Infrastructure) -> MetaTask:
    return MetaTask(
        user_id=db.user_id,
        request=_request(text, db),
        db=db,
        infrastructure=infrastructure,
        tool_registry=registry,
        turns=None,
    )


def run_row(text: str, registry: ToolRegistry, infrastructure: Infrastructure,
            history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """one row through detect_and_setup, with a fresh in-memory conversation"""
    db = TuneDb(history if history is not None else list(NEUTRAL_HISTORY))
    started = time.monotonic()
    result = _meta(text, db, registry, infrastructure).detect_and_setup()
    result["seconds"] = round(time.monotonic() - started, 3)
    result["text"] = text
    result["complexity"] = MessageShape(text).complexity()
    result["where_hit"] = MapTool.text_score(text) > 0
    return result


def _tools_of(calls: Iterable[dict]) -> List[str]:
    return list(dict.fromkeys(call.get("tool") for call in calls if call.get("tool")))


def score_tool(label: str, called: bool) -> Tuple[str, bool]:
    """(kind, ok): kind is M, r, or neg. M and r should be called; unlabelled should not."""
    if label == "M":
        return "M", called
    if label == "r":
        return "r", called
    return "neg", not called


def report(rows: List[dict], tools: List[str], out: Path, title: str, registry=None) -> None:
    """writes tune.out, scores.jsonl, summary.json and levers.json under out, and prints the tables"""
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n",
        encoding="utf-8",
    )
    lines: List[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    n = len(rows)
    total_s = sum(r.get("seconds") or 0 for r in rows)
    sources = Counter(r.get("source") or "none" for r in rows)
    emit(f"{title}: {n} examples, {total_s:.1f}s total, {total_s / n if n else 0:.2f}s per row")
    emit("sources: " + ", ".join(f"{name}={sources[name]}" for name in sorted(sources)))
    emit(f"{'tool':<16}{'labelled':>9}{'M':>6}{'called':>8}  recall     precision   FP")
    per: Dict[str, Any] = {}
    for tool in tools:
        labelled = [r for r in rows if (r.get("labels") or {}).get(tool) in ("M", "r")]
        mandatory = [r for r in rows if (r.get("labels") or {}).get(tool) == "M"]
        unlabelled = [r for r in rows if (r.get("labels") or {}).get(tool) not in ("M", "r")]
        tp = [r for r in labelled if tool in (r.get("called") or [])]
        fp = [r for r in unlabelled if tool in (r.get("called") or [])]
        fn = [r for r in labelled if tool not in (r.get("called") or [])]
        m_ok = [r for r in mandatory if tool in (r.get("called") or [])]
        recall = len(tp) / len(labelled) if labelled else None
        precision = len(tp) / (len(tp) + len(fp)) if (tp or fp) else None
        rec_s = f"{len(tp)}/{len(labelled)}" if labelled else "—"
        pre_s = f"{len(tp)}/({len(tp)}+{len(fp)})" if (tp or fp) else "—"
        emit(f"{tool:<16}{len(labelled):>5}    {len(m_ok):>2}/{len(mandatory):<2} {len(tp)+len(fp):>6}  "
             f"{rec_s:<10} {pre_s:<11} {len(fp)}")
        per[tool] = {
            "labelled": len(labelled), "mandatory": len(mandatory), "mandatory_called": len(m_ok),
            "tp": len(tp), "fp": len(fp), "fn": len(fn), "recall": recall, "precision": precision,
            "misses": [{"line": r.get("line"), "text": r.get("text"), "label": (r.get("labels") or {}).get(tool),
                        "source": r.get("source"), "called": r.get("called")} for r in fn],
            "false_positives": [{"line": r.get("line"), "text": r.get("text"), "source": r.get("source"),
                                 "called": r.get("called")} for r in fp],
        }

    emit()
    emit("notable misses and false positives (labelled tools plus websearch):")
    focus = [tool for tool in tools if per[tool]["labelled"] or tool == "websearch"]
    for tool in focus:
        rec = per[tool]
        if not rec["misses"] and not rec["false_positives"]:
            continue
        emit(f"\n{tool}  recall {rec['tp']}/{rec['labelled']}  FP {rec['fp']}")
        for item in rec["misses"][:12]:
            emit(f"  MISS  {item.get('source') or '-'}  {item['text']}")
        for item in rec["false_positives"][:8]:
            emit(f"  FP    {item.get('source') or '-'}  {item['text']}")
        if len(rec["false_positives"]) > 8:
            emit(f"  ... {len(rec['false_positives']) - 8} more FPs")

    advisor = LeverAdvisor(rows, registry, tools=tools)
    payload = advisor.recommend()
    (out / "levers.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    emit()
    emit(advisor.table(payload))

    (out / "tune.out").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "n": n, "seconds": total_s, "per_row": total_s / n if n else 0, "sources": dict(sources),
        "tools": per,
        "levers": payload,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    emit(f"wrote {out / 'tune.out'}, scores.jsonl, summary.json, levers.json")


def load_rows(path: Path, limit: Optional[int] = None) -> Tuple[List[dict], List[dict]]:
    examples, malformed = [], []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            malformed.append({"line": i, "reason": "empty line"})
            continue
        try:
            obj = json.loads(line)
        except Exception as e:
            malformed.append({"line": i, "reason": f"invalid json: {e}"})
            continue
        examples.append({"line": i, **obj})
        if limit is not None and len(examples) >= limit:
            break
    return examples, malformed


def run_dataset(path: Path, out: Path, *, infrastructure: Infrastructure, registry: ToolRegistry,
                tools: List[str], limit: Optional[int] = None, followup: bool = False,
                title: Optional[str] = None) -> List[dict]:
    examples, malformed = load_rows(path, limit)
    print(f"{path.name}: {len(examples)} ok, {len(malformed)} malformed")
    progress = Progress()
    progress.start(f"scoring {path.name}: {len(examples)} examples")
    rows = []
    for n, example in enumerate(examples, 1):
        text = example["text"]
        history = prior_messages(text, example.get("followup") or "") if followup else list(NEUTRAL_HISTORY)
        try:
            result = run_row(text, registry, infrastructure, history=history)
        except Exception as e:
            result = {"text": text, "source": "error", "called": [], "calls": [], "scores": {},
                      "laya_scores": {}, "text_scores": {}, "gate": {}, "followup_score": 0,
                      "project": 0, "picked": None, "tool_names": [], "recommended": [],
                      "offered_mandatory": [], "offered_recommended": [], "seconds": 0, "error": repr(e)}
        result["line"] = example["line"]
        result["labels"] = example.get("labels") or {}
        result["followup_phrase"] = example.get("followup")
        rows.append(result)
        progress.row(n, len(examples), short_label(text), _stack_outcome(result))
    progress.done()
    report(rows, tools, out, title or path.name, registry=registry)
    return rows


def _stack_outcome(result: dict) -> str:
    """source and the tools that were called, or the error, for the progress line"""
    if result.get("error"):
        return f"error {result['error']}"
    called = ",".join(result.get("called") or []) or "—"
    return f"{result.get('source') or 'none'}  called={called}"


def _chat_request_works() -> bool:
    """False when ChatRequest is the host test stub (pydantic was not installed)"""
    try:
        ChatRequest(contact_id=1, conversation_id=1, role="user", name="user", content="x", temperature=0.0)
        return True
    except TypeError:
        return False


def run(out: Path, *, dataset: Path, followup: Optional[Path] = None, limit: Optional[int] = None) -> None:
    logging.disable(logging.INFO)
    if not _chat_request_works():
        raise RuntimeError("stack mode needs a real ChatRequest (install pydantic and json-repair; "
                           "the host test venv stubs them)")
    infrastructure = stack_infrastructure()
    queue = TaskQueue()
    registry = ToolRegistry(None, infrastructure, queue, execute_tools=False)
    from app.tasks.tool_detection_task import ToolDetectionTask
    tools = sorted({key.rsplit("__", 1)[0] for key in ToolDetectionTask("", registry, None)._questions()})
    print("stack mode, tools are recorded not executed")
    print("nodes:", {name: f"{n.addr}:{n.port}" for name, n in infrastructure.node_by_type.items()})
    progress = Progress()
    progress.start("stack tune")
    run_dataset(dataset, out, infrastructure=infrastructure, registry=registry, tools=tools,
                limit=limit, title=dataset.name)
    if followup is not None and followup.exists():
        run_dataset(followup, out / "followup", infrastructure=infrastructure, registry=registry, tools=tools,
                    limit=limit, followup=True, title=followup.name)
    progress.done()
