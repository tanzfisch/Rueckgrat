"""
Tests the scenarios in dataset.jsonl with the questions currently in the tools' code and prints how well each tool's
questions did plus a threshold recommendation per tool. Run ./laya_tune/tune.sh from hub/ (see README.md).
"""
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

from app.tasks.tool_detection_task import ToolDetectionTask     # imports the task package first, like the hub
from app.tools.tool_registry import ToolRegistry
from app.utils.infrastructure import Infrastructure

DATASET = Path(__file__).parent / "dataset.jsonl"
LAYA = os.environ.get("LAYA_DECIDE", "192.168.2.158:7346")     # host:port of the text_to_decision node
GRID = [round(x * 0.05, 2) for x in range(4, 20)]      # 0.20 .. 0.95
MIN_POSITIVES = 3       # fewer labelled examples of a tool: no threshold recommendation


def correct(label: str, score: float, thresholds: Tuple[float, float]) -> bool:
    """M: must reach mandatory. r: must reach recommended. no label: must stay below recommended"""
    recommended, mandatory = thresholds
    if label == "M":
        return score >= mandatory
    if label == "r":
        return score >= recommended
    return score < recommended


def hits(examples: List[dict], tool: str, scores: List[Dict[str, float]], thresholds: Tuple[float, float]) -> int:
    return sum(correct(e["labels"].get(tool, ""), s.get(tool, 0.0), thresholds) for e, s in zip(examples, scores))


def best_thresholds(examples: List[dict], tool: str, scores: List[Dict[str, float]], current: Tuple[float, float]) -> Tuple[float, float]:
    """the (recommended, mandatory) pair with the most correct examples, the one nearest the current pair on a tie"""
    pairs = [(r, m) for m in GRID if m >= 0.5 for r in GRID if r < m]
    distance = lambda pair: abs(pair[0] - current[0]) + abs(pair[1] - current[1])
    return max(pairs, key=lambda pair: (hits(examples, tool, scores, pair), -distance(pair)))


def tool_scores(text: str, registry: ToolRegistry, infrastructure: Infrastructure) -> Dict[str, float]:
    """each tool's score as the hub's ToolDetectionTask gets it: the best of its questions, also on the whole message
    (Tool.whole_message), and its Tool.text_score"""
    task = ToolDetectionTask(text, registry, infrastructure)
    task.execute()
    return task.tool_scores()


def main():
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
        scores = [tool_scores(e["text"], registry, infrastructure) for e in examples]
        print(f"{'tool':<16}{'current':<14}{'correct':>9}  recommended thresholds")
        total = 0
        for tool in tools:
            current = detection.thresholds(tool)
            now = hits(examples, tool, scores, current)
            total += now
            line = f"{tool:<16}{str(current):<14}{now:>4}/{len(examples):<4}  "
            if sum(tool in e["labels"] for e in examples) < MIN_POSITIVES:
                line += f"{current} -> {now}/{len(examples)} (fewer than {MIN_POSITIVES} labelled examples)"
            else:
                pair = best_thresholds(examples, tool, scores, current)
                line += f"{pair} -> {hits(examples, tool, scores, pair)}/{len(examples)}"
            print(line)
        print(f"{'all tools':<16}{total:>4}/{len(examples) * len(tools):<4}  {100 * total / (len(examples) * len(tools)):.1f}%")


if __name__ == "__main__":
    main()
