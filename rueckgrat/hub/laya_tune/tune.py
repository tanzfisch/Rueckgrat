"""
Tests the scenarios in dataset.jsonl. The default mode scores Laya's per-tool questions and prints a threshold
recommendation per tool. --stack runs MetaTask detection and the tool setup rounds (the model decides which tools
to call; the tools are recorded and not executed). Run ./laya_tune/tune.sh from hub/ (see README.md).
"""
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

from .progress import Progress, short_label

from app.tasks.tool_detection_task import (     # imports the task package first, like the hub
    ToolDetectionTask, FOLLOWUP_QUESTION, FOLLOWUP_RECOMMENDED_THRESHOLD as FOLLOWUP_RECOMMENDED,
    FOLLOWUP_MANDATORY_THRESHOLD as FOLLOWUP_MANDATORY,
)
from app.tools.tool_registry import ToolRegistry
from app.utils.infrastructure import Infrastructure

DATASET = Path(__file__).parent / "dataset.jsonl"
FOLLOWUP_DATASET = Path(__file__).parent / "followup.jsonl"
LAYA = os.environ.get("LAYA_DECIDE", "192.168.2.158:7346")     # host:port of the text_to_decision node
GRID = [round(x * 0.05, 2) for x in range(4, 20)]      # 0.20 .. 0.95
MIN_POSITIVES = 3       # fewer labelled examples of a tool: no threshold recommendation
MANDATORY_FACTOR = 1.0  # the derived mandatory is raised by this, at most 1.0 (1.0 keeps the grid winner; then a tool is only ever recommended when the winner is already 1.0)
# thresholds set by hand, not proposed by this tuner (websearch: offered often, never forced)
MANUAL_THRESHOLDS = frozenset({"websearch"})


def correct(label: str, score: float, thresholds: Tuple[float, float]) -> bool:
    """M: must reach mandatory. r: must reach recommended. no label: must stay below recommended.
    when mandatory is 1.0 the tool is recommended-only (never forced): an M label only needs to reach recommended"""
    recommended, mandatory = thresholds
    if label == "M":
        return score >= (recommended if mandatory >= 1.0 else mandatory)
    if label == "r":
        return score >= recommended
    return score < recommended


def hits(examples: List[dict], tool: str, scores: List[Dict[str, float]], thresholds: Tuple[float, float]) -> int:
    return sum(correct(e["labels"].get(tool, ""), s.get(tool, 0.0), thresholds) for e, s in zip(examples, scores))


def best_thresholds(examples: List[dict], tool: str, scores: List[Dict[str, float]], current: Tuple[float, float]) -> Tuple[float, float]:
    """the (recommended, mandatory) pair with the most correct examples, the one nearest the current pair on a tie.
    mandatory is then raised by MANDATORY_FACTOR, at most 1.0, recommended is unchanged"""
    pairs = [(r, m) for m in GRID if m >= 0.5 for r in GRID if r < m]
    distance = lambda pair: abs(pair[0] - current[0]) + abs(pair[1] - current[1])
    recommended, mandatory = max(pairs, key=lambda pair: (hits(examples, tool, scores, pair), -distance(pair)))
    return recommended, min(1.0, round(mandatory * MANDATORY_FACTOR, 2))


def tool_scores(text: str, registry: ToolRegistry, infrastructure: Infrastructure) -> Dict[str, float]:
    """each tool's laya and text score, always from the per-tool questions (ToolDetectionTask.score_tool_questions):
    the best of its questions, also on the whole message (Tool.whole_message), and its Tool.text_score. the hub's
    follow-up path is not used, so a follow-up row is still scored per tool"""
    task = ToolDetectionTask(text, registry, infrastructure)
    return task.score_tool_questions()


def _laya_outcome(scores: Dict[str, float]) -> str:
    """the highest per-tool scores of a row, for the progress line"""
    top = [(name, p) for name, p in sorted(scores.items(), key=lambda item: -item[1]) if p > 0][:3]
    return " ".join(f"{name}={p:.2f}" for name, p in top) or "—"


def run_laya():
    logging.disable(logging.INFO)    # the hub's debug and info logs, warnings and errors still show
    host, port = LAYA.rsplit(":", 1)
    infrastructure = Infrastructure.__new__(Infrastructure)     # no config, no node connections: only decide is used
    infrastructure.node_by_type = {"text_to_decision": SimpleNamespace(addr=host, port=int(port))}
    registry = ToolRegistry(None, None, None)
    detection = ToolDetectionTask("", registry, None)
    tools = sorted({key.rsplit("__", 1)[0] for key in detection._questions()})

    by_lang = defaultdict(list)
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            example = json.loads(line)
            by_lang[example["lang"]].append(example)

    for lang, examples in sorted(by_lang.items()):
        print(f"\n{lang}: {len(examples)} examples, thresholds are (recommended, mandatory)")
        progress = Progress()
        progress.start(f"scoring {lang}: {len(examples)} examples")
        scores = []
        for n, example in enumerate(examples, 1):
            row = tool_scores(example["text"], registry, infrastructure)
            scores.append(row)
            progress.row(n, len(examples), short_label(example["text"]), _laya_outcome(row))
        progress.done()
        print(f"{'tool':<16}{'current':<14}{'correct':>9}  recommended thresholds")
        total = 0
        for tool in tools:
            current = detection.thresholds(tool)
            now = hits(examples, tool, scores, current)
            total += now
            line = f"{tool:<16}{str(current):<14}{now:>4}/{len(examples):<4}  "
            if tool in MANUAL_THRESHOLDS:
                note = "manual, recommended-only" if current[1] >= 1.0 else "manual"
                line += f"{current} ({note})"
            elif sum(tool in e["labels"] for e in examples) < MIN_POSITIVES:
                line += f"{current} -> {now}/{len(examples)} (fewer than {MIN_POSITIVES} labelled examples)"
            else:
                pair = best_thresholds(examples, tool, scores, current)
                line += f"{pair} -> {hits(examples, tool, scores, pair)}/{len(examples)}"
            print(line)
        print(f"{'all tools':<16}{total:>4}/{len(examples) * len(tools):<4}  {100 * total / (len(examples) * len(tools)):.1f}%")

    report_followup(infrastructure)


def followup_noul(text: str, infrastructure: Infrastructure) -> float:
    """the follow-up question alone (one decide call), the same wording the hub asks in the gate batch"""
    task = ToolDetectionTask(text, ToolRegistry(None, None, None), infrastructure)
    decided = infrastructure.decide(text, task._followup_questions())
    return task._followup_score(decided or {})


def followup_correct(label: str, score: float, recommended: float, mandatory: float) -> bool:
    """M: must reach mandatory. r: must reach recommended. no label: must stay below recommended"""
    if label == "M":
        return score >= mandatory
    if label == "r":
        return score >= recommended
    return score < recommended


def report_followup(infrastructure: Infrastructure) -> None:
    """each followup.jsonl example's noul, and how 0.5 / 0.7 (and a nearby pair) classify them.
    dataset.jsonl is left alone: these messages are not tool-labelled rows"""
    if not FOLLOWUP_DATASET.exists():
        return
    examples = [json.loads(line) for line in FOLLOWUP_DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not examples:
        return
    recommended, mandatory = FOLLOWUP_RECOMMENDED, FOLLOWUP_MANDATORY
    print()
    print(f"follow-up question, {len(examples)} examples, thresholds ({recommended}, {mandatory})")
    print(FOLLOWUP_QUESTION)
    progress = Progress()
    progress.start(f"scoring follow-up: {len(examples)} examples")
    scores = []
    hits_now = 0
    for n, example in enumerate(examples, 1):
        score = followup_noul(example["text"], infrastructure)
        scores.append(score)
        label = example.get("followup") or ""
        ok = followup_correct(label, score, recommended, mandatory)
        hits_now += ok
        mark = "ok" if ok else "miss"
        want = {"M": "mandatory", "r": "recommended"}.get(label, "below recommended")
        print(f"  {score:.4f}  {mark:4}  want {want:<18}  {example['text']}")
        progress.row(n, len(examples), short_label(example["text"]),
                     f"{score:.3f} {label or '-'} {mark}")
    progress.done(f"{hits_now}/{len(examples)}")
    print(f"at ({recommended}, {mandatory}): {hits_now}/{len(examples)}")

    # a nearby pair, for the report: does a slightly lower recommended catch more follow-ups without new false positives
    alts = [(0.45, 0.65), (0.45, 0.70), (0.40, 0.70), (0.50, 0.65)]
    for rec, man in alts:
        n = sum(followup_correct(e.get("followup") or "", s, rec, man) for e, s in zip(examples, scores))
        print(f"at ({rec}, {man}): {n}/{len(examples)}")


def main(argv=None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description="laya_tune: Laya questions (default) or the whole tool stack (--stack)")
    parser.add_argument("--stack", action="store_true",
                        help="measure detection plus setup rounds, not Laya scores alone")
    parser.add_argument("--out", type=Path, default=None,
                        help="folder for tune.out, scores.jsonl, summary.json and levers.json (required for --stack)")
    parser.add_argument("--followup", action="store_true",
                        help="with --stack, also run followup.jsonl")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N rows of each file (a short run)")
    args = parser.parse_args(argv)
    if args.stack:
        if args.out is None:
            parser.error("--stack needs --out DIR")
        from .stack_tune import run
        run(args.out, dataset=DATASET, followup=FOLLOWUP_DATASET if args.followup else None, limit=args.limit)
        return
    if args.out or args.followup or args.limit:
        parser.error("--out, --followup and --limit are for --stack")
    run_laya()


if __name__ == "__main__":
    main()
