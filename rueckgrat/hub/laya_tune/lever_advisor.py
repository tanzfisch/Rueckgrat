"""
Offline recommendations for every detection and setup lever, from a stack-mode run's recorded scores.
Nothing is applied: the table and levers.json are for review.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.tasks.meta_task import MetaTask
from app.tasks.tool_detection_task import (
    GATE_THRESHOLD,
    FOLLOWUP_RECOMMENDED_THRESHOLD,
    FOLLOWUP_MANDATORY_THRESHOLD,
    RECOMMENDED_THRESHOLD,
    MANDATORY_THRESHOLD,
    PICK_MAX_TOKENS,
    PICK_TIMEOUT,
    PICK_TEXT_CHARS,
    PICK_DESCRIPTION_CHARS,
    ToolDetectionTask,
)
from app.tasks.tool_execution_task import ToolExecutionTask
from app.tools.map_tool import WHERE_SCORE
from app.tools.search_memory_tool import CONVERSATION_THRESHOLD
from app.tools.spawn_agent_job_tool import JOB_COMPLEXITY

from .progress import Progress
from .tune import MANDATORY_FACTOR, MANUAL_THRESHOLDS, MIN_POSITIVES, correct as laya_correct

TOOL_GRID = [round(x * 0.05, 2) for x in range(2, 21)]     # 0.10 .. 1.00
GATE_GRID = [round(x * 0.05, 2) for x in range(10, 20)]    # 0.50 .. 0.95
FOLLOWUP_REC_GRID = [round(x * 0.05, 2) for x in range(4, 15)]
FOLLOWUP_MAN_GRID = [round(x * 0.05, 2) for x in range(8, 19)]
JOB_GRID = [round(x * 0.05, 2) for x in range(4, 13)]      # 0.20 .. 0.60
WHERE_GRID = [0.45, 0.5, 0.55, 0.59, 0.6, 0.65, 0.7]
ROW_CAP = 15


class LeverAdvisor:
    """one-at-a-time lever recommendations from recorded per-row scores, without another LLM call"""

    def __init__(self, rows: List[dict], registry=None, thresholds: Optional[Dict[str, Tuple[float, float]]] = None,
                 tools: Optional[Sequence[str]] = None):
        self.rows = list(rows)
        self.registry = registry
        self.thresholds = {name: (float(pair[0]), float(pair[1])) for name, pair in
                           (thresholds or self._current_thresholds()).items()}
        self.tools = list(tools) if tools is not None else self._tool_names()

    def _current_thresholds(self) -> Dict[str, Tuple[float, float]]:
        if self.registry is None:
            return {}
        detection = ToolDetectionTask("", self.registry, None)
        names = {key.rsplit("__", 1)[0] for key in detection._questions()}
        names.update(self.registry.tools)
        return {name: detection.thresholds(name) for name in sorted(names)}

    def _tool_names(self) -> List[str]:
        names = set(self.thresholds)
        for row in self.rows:
            names.update((row.get("labels") or {}))
            names.update((row.get("laya_scores") or {}))
            names.update((row.get("text_scores") or {}))
            names.update((row.get("called") or []))
        drop = set()
        if self.registry is not None:
            drop.update(self.registry.CHAT_EXCLUDED_TOOLS)
            drop.update(self.registry.REPLY_TOOLS)
        return [name for name in sorted(names) if name not in drop]

    def _has_tool_labels(self) -> bool:
        """True when at least one row has a tool labelled M or r. followup.jsonl has none, so per-tool and gate
        levers are not proposed for it"""
        return any(label in ("M", "r") for row in self.rows for label in (row.get("labels") or {}).values())

    def recommend(self) -> Dict[str, Any]:
        """the machine-readable report. apply is always false"""
        progress = Progress()
        progress.start(f"lever advisor: {len(self.rows)} rows, {len(self.tools)} tools")
        baseline = self._tally(self._simulate({}))
        levers = []
        labelled = self._has_tool_labels()
        if labelled:
            levers.extend(self._tool_threshold_levers(baseline))
            levers.append(self._search_lever(
                "GATE_THRESHOLD", GATE_THRESHOLD, GATE_GRID,
                lambda value: {"gate": value},
                baseline, held=True,
                note="held at 0.8 unless Martin decides; recommendation only",
            ))
        levers.append(self._followup_lever(baseline))
        levers.append(self._project_lever())
        levers.append(self._mandatory_factor_lever())
        levers.append(self._search_lever(
            "JOB_COMPLEXITY", JOB_COMPLEXITY, JOB_GRID,
            lambda value: {"job_complexity": value},
            baseline,
            note="text_score recommends spawn_job when MessageShape.complexity reaches this",
        ))
        levers.append(self._search_lever(
            "WHERE_SCORE", WHERE_SCORE, WHERE_GRID,
            lambda value: {"where_score": value},
            baseline,
            note="text_score of a short 'where is X'; 0.6 is at show_map's mandatory threshold",
        ))
        levers.extend(self._unsimulated_levers())
        payload = {
            "apply": False,
            "note": ("Recommendations only, one lever at a time, not applied. Simulated from recorded "
                     "gate, follow-up, laya, text and pick scores. A newly offered recommended tool is not "
                     "assumed called; a call is dropped when the tool would no longer be offered; a tool that "
                     "becomes newly mandatory is treated as called."),
            "metric": "correct tool-row verdicts from simulated calls vs labels (M and r should be called)",
            "baseline": baseline["summary"],
            "levers": levers,
        }
        progress.done(f"{len(levers)} levers")
        return payload

    def table(self, payload: Optional[Dict[str, Any]] = None) -> str:
        payload = payload or self.recommend()
        lines = [
            "Recommendations (not applied)",
            f"{'lever':<32}{'current':<16}{'recommended':<16}{'gain':>5}  {'conf':<8}  notes",
        ]
        for item in payload["levers"]:
            current = _fmt(item["current"])
            recommended = _fmt(item["recommended"])
            ev = item.get("evidence") or {}
            gain = ev.get("expected_gain")
            gain_s = "—" if gain is None else (f"{gain:+d}" if isinstance(gain, int) else str(gain))
            held = " (held)" if item.get("held") else ""
            notes = ev.get("notes") or item.get("note") or ""
            lines.append(f"{item['id'] + held:<32}{current:<16}{recommended:<16}{gain_s:>5}  "
                         f"{item.get('confidence') or 'none':<8}  {notes}")
        lines.append("wrote levers.json (recommendations only, not applied)")
        return "\n".join(lines)

    def _unsimulated_levers(self) -> List[dict]:
        note = "cannot be resimulated from recorded scores; needs a re-run"
        items = [
            ("default_thresholds", (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD),
             "tools without their own pair; also the project question uses RECOMMENDED_THRESHOLD. "
             "no chat-turn tool in this run uses the defaults alone"),
            ("FIND_TOOLS_STEPS", ToolExecutionTask.FIND_TOOLS_STEPS, note),
            ("SETUP_HISTORY", MetaTask.SETUP_HISTORY, note),
            ("HISTORY_CHARS", ToolExecutionTask.HISTORY_CHARS, note),
            ("PICK_MAX_TOKENS", PICK_MAX_TOKENS, note),
            ("PICK_TIMEOUT", PICK_TIMEOUT, note),
            ("PICK_TEXT_CHARS", PICK_TEXT_CHARS, note),
            ("PICK_DESCRIPTION_CHARS", PICK_DESCRIPTION_CHARS, note),
            ("CONVERSATION_THRESHOLD", CONVERSATION_THRESHOLD,
             "search_memory drops conversations below this; tools are not executed in stack mode"),
        ]
        levers = []
        for name, current, text in items:
            levers.append({
                "id": name,
                "current": _jsonable(current),
                "recommended": _jsonable(current),
                "apply": False,
                "confidence": "none",
                "evidence": {"expected_gain": None, "unit": None, "rows_changed": [],
                             "rows_changed_count": 0, "notes": text},
                "note": text,
            })
        return levers

    def _project_lever(self) -> dict:
        asked = sum(1 for row in self.rows if (row.get("project") or 0) > 0)
        text = ("the project questions use RECOMMENDED_THRESHOLD (0.5). stack mode has no volume, so they "
                "were not asked and this lever cannot be simulated")
        if asked:
            text = (f"the project questions use RECOMMENDED_THRESHOLD (0.5). {asked} rows have a project score; "
                    "stack mode has no volume, so the project boost was not applied and the lever cannot be simulated")
        return {
            "id": "project_threshold",
            "current": RECOMMENDED_THRESHOLD,
            "recommended": RECOMMENDED_THRESHOLD,
            "apply": False,
            "confidence": "none",
            "evidence": {"expected_gain": None, "unit": None, "rows_changed": [],
                         "rows_changed_count": 0, "notes": text, "rows_with_project_score": asked},
            "note": text,
        }

    def _mandatory_factor_lever(self) -> dict:
        """compare official laya hits of each tool's best pair with and without the 1.2 inflation"""
        scored = 0
        worse = []
        same = 0
        better = 0
        gain = 0
        for tool, current in self.thresholds.items():
            labels = sum(1 for row in self.rows if (row.get("labels") or {}).get(tool) in ("M", "r"))
            if labels < MIN_POSITIVES or tool in MANUAL_THRESHOLDS:
                continue
            scores = [_detection_score(row, tool) for row in self.rows]
            if not any(scores):
                continue
            scored += 1
            raw = _best_laya_pair(self.rows, tool, scores, current, factor=1.0)
            inflated = (raw[0], min(1.0, round(raw[1] * MANDATORY_FACTOR, 2)))
            hits_raw = _laya_hits(self.rows, tool, scores, raw)
            hits_inf = _laya_hits(self.rows, tool, scores, inflated)
            delta = hits_inf - hits_raw
            gain += delta
            if delta < 0:
                worse.append({"tool": tool, "raw": list(raw), "inflated": list(inflated),
                              "hits_raw": hits_raw, "hits_inflated": hits_inf})
            elif delta > 0:
                better += 1
            else:
                same += 1
        recommended = 1.0 if worse and gain <= 0 else MANDATORY_FACTOR
        if not scored:
            text = "not enough labelled tools with recorded scores to compare 1.2 vs 1.0"
            confidence = "none"
        elif recommended == 1.0:
            text = (f"raising the grid winner by 1.2 worsened official Laya hits on {len(worse)} tool(s) "
                    f"({-gain} fewer correct bands); 1.0 keeps the grid winner")
            confidence = "medium"
        else:
            text = f"inflation did not lose official Laya hits ({scored} tools, {better} improved, {same} unchanged)"
            confidence = "medium"
        return {
            "id": "MANDATORY_FACTOR",
            "current": MANDATORY_FACTOR,
            "recommended": recommended,
            "apply": False,
            "confidence": confidence,
            "evidence": {
                "expected_gain": None if not scored else (0 if recommended == MANDATORY_FACTOR else -gain),
                "unit": "official Laya band hits across tools (grid winner vs winner * 1.2)",
                "tools_scored": scored,
                "tools_worse": worse,
                "rows_changed": [],
                "rows_changed_count": 0,
                "notes": text,
            },
            "note": "proposal convention in laya_tune, not a live hub constant",
        }

    def _followup_lever(self, baseline: dict) -> dict:
        current = (FOLLOWUP_RECOMMENDED_THRESHOLD, FOLLOWUP_MANDATORY_THRESHOLD)
        pairs = [(r, m) for m in FOLLOWUP_MAN_GRID for r in FOLLOWUP_REC_GRID if r < m]
        best, ev = self._best_pair(current, pairs, lambda pair: {"followup": pair}, baseline)
        ev["notes"] = ev.get("notes") or _pair_note(current, best, ev)
        return {
            "id": "followup_thresholds",
            "current": list(current),
            "recommended": list(best),
            "apply": False,
            "confidence": ev.pop("confidence"),
            "evidence": ev,
        }

    def _tool_threshold_levers(self, baseline: dict) -> List[dict]:
        levers = []
        pairs = [(r, m) for m in TOOL_GRID for r in TOOL_GRID if r < m]
        for tool, current in self.thresholds.items():
            if tool not in self.tools:
                continue
            labels = sum(1 for row in self.rows if (row.get("labels") or {}).get(tool) in ("M", "r"))
            fps = sum(1 for row in self.rows if (row.get("labels") or {}).get(tool) not in ("M", "r")
                      and tool in (row.get("called") or []))
            if tool in MANUAL_THRESHOLDS:
                text = "manual, report only, not proposed"
                levers.append({
                    "id": f"{tool}.thresholds",
                    "current": list(current),
                    "recommended": list(current),
                    "apply": False,
                    "manual": True,
                    "fixed": True,
                    "confidence": "none",
                    "evidence": {"expected_gain": 0, "unit": baseline["summary"].get("unit"),
                                 "labelled": labels, "rows_changed": [], "rows_changed_count": 0, "notes": text},
                    "note": text,
                })
                continue
            if labels < MIN_POSITIVES and not fps:
                text = f"fewer than {MIN_POSITIVES} labelled examples ({labels})"
                levers.append({
                    "id": f"{tool}.thresholds",
                    "current": list(current),
                    "recommended": list(current),
                    "apply": False,
                    "manual": tool in MANUAL_THRESHOLDS,
                    "confidence": "none" if labels == 0 else "low",
                    "evidence": {"expected_gain": 0, "unit": baseline["summary"].get("unit"),
                                 "labelled": labels, "rows_changed": [], "rows_changed_count": 0, "notes": text},
                    "note": text,
                })
                continue
            best, ev = self._best_pair(
                current, pairs, lambda pair, name=tool: {"thresholds": {name: pair}}, baseline)
            extra = self._newly_offered(tool, current, best)
            notes = []
            if extra:
                notes.append(f"{len(extra)} more labelled row(s) would be offered; calls unknown")
                ev["newly_offered_labelled"] = extra[:ROW_CAP]
            notes.append(_pair_note(current, best, ev))
            ev["notes"] = "; ".join(n for n in notes if n)
            ev["labelled"] = labels
            levers.append({
                "id": f"{tool}.thresholds",
                "current": list(current),
                "recommended": list(best),
                "apply": False,
                "manual": tool in MANUAL_THRESHOLDS,
                "confidence": ev.pop("confidence"),
                "evidence": ev,
            })
        return levers

    def _search_lever(self, name: str, current: float, grid: Sequence[float],
                      overrides, baseline: dict, held: bool = False, note: str = "") -> dict:
        best_value = current
        best_tally = baseline
        best_gain = 0
        for value in grid:
            tally = self._tally(self._simulate(overrides(value)))
            gain = tally["summary"]["correct"] - baseline["summary"]["correct"]
            closer = (abs(value - current),) < (abs(best_value - current),)
            if gain > best_gain or (gain == best_gain and (value == current or (best_value != current and closer))):
                best_gain, best_value, best_tally = gain, value, tally
        ev = self._evidence(baseline, best_tally, best_gain)
        ev["notes"] = (note + ("; " if note else "")) + _value_note(current, best_value, ev)
        item = {
            "id": name,
            "current": current,
            "recommended": best_value,
            "apply": False,
            "confidence": ev.pop("confidence"),
            "evidence": ev,
            "note": note,
        }
        if held:
            item["held"] = True
        return item

    def _newly_offered(self, tool: str, current: Tuple[float, float], recommended: Tuple[float, float]) -> List[dict]:
        """labelled rows that would first reach recommended, whose call cannot be assumed"""
        if recommended[0] >= current[0]:
            return []
        items = []
        for row, state in zip(self.rows, self._simulate({"thresholds": {tool: recommended}})):
            if (row.get("labels") or {}).get(tool) not in ("M", "r"):
                continue
            if tool in (row.get("called") or []):
                continue
            if tool in state["offered"] and tool not in self._row_offered(row, {}):
                items.append(_row_ref(row, f"{tool} newly offered (call unknown)"))
        return items

    def _best_pair(self, current: Tuple[float, float], pairs: Iterable[Tuple[float, float]],
                   overrides, baseline: dict) -> Tuple[Tuple[float, float], dict]:
        best = current
        best_tally = baseline
        best_gain = 0
        for pair in pairs:
            tally = self._tally(self._simulate(overrides(pair)))
            gain = tally["summary"]["correct"] - baseline["summary"]["correct"]
            closer = (abs(pair[0] - current[0]) + abs(pair[1] - current[1])) < (
                abs(best[0] - current[0]) + abs(best[1] - current[1]))
            if gain > best_gain or (gain == best_gain and (pair == current or (best != current and closer))):
                best_gain, best, best_tally = gain, pair, tally
        return best, self._evidence(baseline, best_tally, best_gain)

    def _evidence(self, baseline: dict, tally: dict, gain: int) -> dict:
        changed = []
        for row, before, after in zip(self.rows, baseline["states"], tally["states"]):
            if before["called"] != after["called"] or before["offered"] != after["offered"] or \
                    before["path"] != after["path"] or before["skip"] != after["skip"]:
                detail = []
                if before["skip"] != after["skip"]:
                    detail.append("skip" if after["skip"] else "no longer skipped")
                if before["path"] != after["path"]:
                    detail.append(f"path {before['path']} -> {after['path']}")
                lost = sorted(before["called"] - after["called"])
                gained = sorted(after["called"] - before["called"])
                if lost:
                    detail.append("drop " + ", ".join(lost))
                if gained:
                    detail.append("add " + ", ".join(gained))
                if not detail and before["offered"] != after["offered"]:
                    detail.append("offers changed")
                changed.append(_row_ref(row, "; ".join(detail)))
        unsim = tally["summary"]["unsimulatable"]
        if unsim and gain:
            confidence = "medium"
        elif unsim:
            confidence = "medium"
        else:
            confidence = "high"
        return {
            "expected_gain": gain,
            "unit": "correct tool-row verdicts (simulated calls vs labels)",
            "current_correct": baseline["summary"]["correct"],
            "recommended_correct": tally["summary"]["correct"],
            "rows_changed": changed[:ROW_CAP],
            "rows_changed_count": len(changed),
            "unsimulatable": unsim,
            "confidence": confidence,
        }

    def _tally(self, states: List[dict]) -> dict:
        correct = 0
        total = 0
        tp = fp = fn = 0
        unsim = 0
        for row, state in zip(self.rows, states):
            unsim += int(bool(state.get("unsimulatable")))
            called = state["called"]
            for tool in self.tools:
                total += 1
                label = (row.get("labels") or {}).get(tool, "")
                hit = tool in called
                if label in ("M", "r"):
                    correct += int(hit)
                    tp += int(hit)
                    fn += int(not hit)
                else:
                    correct += int(not hit)
                    fp += int(hit)
        return {
            "states": states,
            "summary": {
                "correct": correct,
                "total": total,
                "recall": (tp / (tp + fn)) if (tp + fn) else None,
                "precision": (tp / (tp + fp)) if (tp + fp) else None,
                "tp": tp, "fp": fp, "fn": fn,
                "unsimulatable": unsim,
                "unit": "correct tool-row verdicts (simulated calls vs labels)",
            },
        }

    def _simulate(self, overrides: dict) -> List[dict]:
        return [self._simulate_row(row, overrides) for row in self.rows]

    def _row_offered(self, row: dict, overrides: dict) -> set:
        return self._simulate_row(row, overrides)["offered"]

    def _simulate_row(self, row: dict, overrides: dict) -> dict:
        thresholds = dict(self.thresholds)
        thresholds.update(overrides.get("thresholds") or {})
        gate_t = overrides.get("gate", GATE_THRESHOLD)
        followup_rec, followup_man = overrides.get("followup", (
            FOLLOWUP_RECOMMENDED_THRESHOLD, FOLLOWUP_MANDATORY_THRESHOLD))
        job_c = overrides.get("job_complexity", JOB_COMPLEXITY)
        where_s = overrides.get("where_score", WHERE_SCORE)

        text = dict(row.get("text_scores") or {})
        if "complexity" in row and row["complexity"] is not None:
            rec = thresholds.get("spawn_job", (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD))[0]
            if row["complexity"] >= job_c:
                text["spawn_job"] = rec
            else:
                text.pop("spawn_job", None)
        if row.get("where_hit"):
            text["show_map"] = where_s
        elif "where_hit" in row:
            text.pop("show_map", None)

        laya = dict(row.get("laya_scores") or {})
        picked = row.get("picked")
        followup = row.get("followup_score")
        if followup is None:
            followup = 0.0
        gate = row.get("gate") or {}
        casual = float(gate.get("chat") or 0.0) + float(gate.get("scene") or 0.0)
        gate_ran = bool(gate)
        laya_asked = bool(laya)
        text_blocks = any(score >= thresholds.get(name, (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD))[0]
                          for name, score in text.items())

        path = "laya"
        skip = False
        unsimulatable = False
        if followup >= followup_man:
            path = "followup_high"
            if picked is None and not text:
                unsimulatable = True
        elif followup >= followup_rec:
            path = "followup_mid"
            if picked is None and not laya_asked:
                unsimulatable = True
        elif (not text_blocks) and gate_ran and casual >= gate_t:
            path = "gate"
            skip = True

        scores: Dict[str, float] = {}
        if path == "gate":
            scores = dict(text)
        elif path == "followup_high":
            scores = dict(text)
            if picked is not None:
                scores = _merge(scores, _pick_floors(picked, thresholds, self.registry))
            if laya_asked:
                # scores stay in the trace only on the high path; do not offer from them
                pass
        else:
            scores = _merge(dict(laya), text)
            if path == "followup_mid" and picked is not None:
                scores = _merge(scores, _pick_floors(picked, thresholds, self.registry))
            elif path == "laya" and not laya_asked and not text:
                # would have been skipped at the current gate, or the per-tool questions never ran
                if gate_ran and not skip:
                    unsimulatable = True

        # a newly unskipped row has no laya scores
        if (not skip) and path == "laya" and (not laya_asked) and gate_ran and casual < gate_t:
            # current run skipped this row (or never asked tools); opening it cannot be scored
            if casual >= GATE_THRESHOLD or row.get("source") == "gate":
                unsimulatable = True

        mandatory, recommended = _bands(scores, thresholds)
        if self.registry is not None:
            mandatory, recommended = self.registry.yielding(mandatory, recommended, row.get("text") or "")
            mandatory, recommended = self.registry.bands(mandatory, recommended)
            excluded = tuple(self.registry.REPLY_TOOLS) + tuple(self.registry.CHAT_EXCLUDED_TOOLS)
            mandatory = mandatory + self.registry.companions(mandatory + recommended, excluded)
            optional = [name for name in self.registry.PROMPT_TOOLS if name not in excluded]
        else:
            optional = []
        offered = set(mandatory) | set(recommended) | set(optional)
        if self.registry is not None:
            offered -= set(self.registry.REPLY_TOOLS)
            offered -= set(self.registry.CHAT_EXCLUDED_TOOLS)

        recorded = list(row.get("called") or [])
        called = {name for name in recorded if name in offered}
        # newly mandatory: the setup tells the model it must call them
        for name in mandatory:
            if name in offered:
                called.add(name)
        return {
            "called": called,
            "offered": offered,
            "mandatory": set(mandatory),
            "path": path,
            "skip": skip,
            "unsimulatable": unsimulatable,
        }


def _detection_score(row: dict, tool: str) -> float:
    return max(float((row.get("laya_scores") or {}).get(tool) or 0.0),
               float((row.get("text_scores") or {}).get(tool) or 0.0))


def _laya_hits(rows: List[dict], tool: str, scores: List[float], pair: Tuple[float, float]) -> int:
    return sum(laya_correct((row.get("labels") or {}).get(tool, ""), score, pair)
               for row, score in zip(rows, scores))


def _best_laya_pair(rows: List[dict], tool: str, scores: List[float],
                    current: Tuple[float, float], factor: float) -> Tuple[float, float]:
    pairs = [(r, m) for m in TOOL_GRID if m >= 0.5 for r in TOOL_GRID if r < m]
    def key(pair):
        return (_laya_hits(rows, tool, scores, pair),
                -(abs(pair[0] - current[0]) + abs(pair[1] - current[1])))
    recommended, mandatory = max(pairs, key=key)
    return recommended, min(1.0, round(mandatory * factor, 2))


def _bands(scores: Dict[str, float], thresholds: Dict[str, Tuple[float, float]]) -> Tuple[List[str], List[str]]:
    mandatory, recommended = [], []
    for name, p in scores.items():
        rec, man = thresholds.get(name, (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD))
        if p >= man:
            mandatory.append(name)
        elif p >= rec:
            recommended.append(name)
    return mandatory, recommended


def _pick_floors(picked: List[str], thresholds: Dict[str, Tuple[float, float]], registry) -> Dict[str, float]:
    priority = set(registry.PRIORITY_TOOLS) if registry is not None else set()
    floors = {}
    for name in picked:
        rec, man = thresholds.get(name, (RECOMMENDED_THRESHOLD, MANDATORY_THRESHOLD))
        floors[name] = man if name in priority else rec
    return floors


def _merge(*maps: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for mapping in maps:
        for name, value in mapping.items():
            out[name] = max(out.get(name, 0.0), float(value))
    return out


def _row_ref(row: dict, change: str) -> dict:
    text = " ".join((row.get("text") or "").split())
    if len(text) > 80:
        text = text[:77] + "..."
    return {"line": row.get("line"), "text": text, "change": change, "source": row.get("source")}


def _pair_note(current, best, ev) -> str:
    if tuple(best) == tuple(current):
        return "already the best of the grid" if ev.get("expected_gain") == 0 else "kept"
    return f"{ev.get('rows_changed_count') or 0} row(s) change"


def _value_note(current, best, ev) -> str:
    if best == current:
        return "already the best of the grid" if ev.get("expected_gain") == 0 else "kept"
    return f"{ev.get('rows_changed_count') or 0} row(s) change"


def _fmt(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"({value[0]}, {value[1]})"
    return str(value)


def _jsonable(value: Any):
    if isinstance(value, tuple):
        return list(value)
    return value
