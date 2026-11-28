# laya_tune

Tests the scenarios in `dataset.jsonl` with the questions currently in the tools' code. It prints, per tool, how
many examples it got right and a recommended (recommended, mandatory) threshold pair. The mandatory it prints is `MANDATORY_FACTOR` (1.0: the grid winner, no inflation) times the derived value, at most 1.0 (then the tool is only ever recommended). `websearch` is set by hand to (0.2, 1.0): offered often, never forced. The tuner reports its score at those thresholds and does not propose a new pair.

```sh
hub/laya_tune/tune.sh
```
Needs the `rueckgrat-hub` image and the laya node (default `192.168.2.158:7346`, change with `LAYA_DECIDE=host:port`). Stack mode also uses `LLM_CHAT`, `IMAGE_NODE`, and `TTS_NODE` (default: the laya node, so `text_to_speech` is scored and can be offered).
It uses the code in `hub/app`, so edited questions count without a rebuild.

Progress is written to stderr, one line per row, and shows live when you run `tune.sh` in a terminal
(python `-u`, `PYTHONUNBUFFERED=1`, and docker `-t` when stdout is a tty). A phase start and end is
logged for each language, the follow-up file, a stack dataset, and the lever advisor, for example
`[12/539] 22.6s/row ETA 3h 2m  What's the capital of Australia  websearch=0.21`. The tables stay on
stdout and in `--out`.

## dataset.jsonl
One example per line: `{"lang": "en", "text": "Quiz me on capitals", "labels": {"poll": "M"}}`
- `"M"`: the tool should be mandatory. `"r"`: recommended or mandatory are both fine.
- A tool that isn't in `labels` should stay below the recommended threshold.
- Results are printed per `lang`.

## chat / scene / work gate
Tool detection asks one choice question first (`GATE_CRITERIA` and `GATE_THRESHOLD` in `tool_detection_task.py`).
This tuner always scores the per-tool noul questions (`ToolDetectionTask.score_tool_questions`), also on a row the
hub would treat as a follow-up; it does not pick a gate threshold. A later run can add
`"gate": "chat"|"scene"|"work"` labels and print P(chat)+P(scene) against that threshold.

## followup.jsonl
A separate file of follow-up and standalone messages, used to score the one follow-up noul question
(`FOLLOWUP_QUESTION` in `tool_detection_task.py`). `dataset.jsonl` is not changed: those rows are labelled by tool,
not by whether the text refers back. One example per line:
`{"lang": "en", "text": "Tell me when the file is ready.", "followup": "M"}`
- `"M"`: the score should reach the mandatory follow-up threshold (0.65). `"r"`: recommended (0.4) or mandatory are both fine.
- An empty `"followup"` is a standalone message and should stay below 0.4.
The tuner prints the score of each example and how many the current (0.4, 0.65) pair gets right.

## stack mode
The default run above scores only Laya's per-tool questions. `--stack` measures the whole chat-turn stack: each
row goes through `MetaTask.detect_and_setup` (the real gate, follow-up, Laya, text scores and the LLM pick) and
`ToolExecutionTask`'s setup rounds (the model decides which offered tools to call). The tools are recorded and
not executed: no web, no sandbox, no jobs. Laya and the LLM are the live nodes, over the same HTTP APIs the hub
uses (`LAYA_DECIDE`, `LLM_CHAT`, or `infrastructure.json`).

A mock in-memory db holds a short earlier exchange (a neutral hello for `dataset.jsonl`; for `followup.jsonl`,
a matching earlier turn when the phrase has a clear antecedent). Nothing is written to the real database.

```sh
hub/laya_tune/tune.sh --stack --out /tmp/t1024
hub/laya_tune/tune.sh --stack --out /tmp/t1024 --followup
hub/laya_tune/tune.sh --stack --out /tmp/t1024 --limit 20
```
`--out` receives `tune.out`, `scores.jsonl`, `summary.json` and `levers.json`. The first table is per tool: recall
and precision of the tools the model actually called, against the labels (`M` and `r` both mean the tool should be
called; `M` is also reported on its own), plus the detection source and the time per row. `--limit N` runs only
the first N rows.

After the score table, stack mode prints a recommendation for every configurable detection or setup lever
(per-tool thresholds, `GATE_THRESHOLD`, the follow-up pair, the project question threshold, `MANDATORY_FACTOR`,
`JOB_COMPLEXITY`, `WHERE_SCORE`, and the setup/pick constants). Each line has the current value, the recommended
value, the expected gain, the rows that would change, and a confidence. Where the recorded per-row scores are
enough, the recommendation is simulated offline, without another LLM call. Newly offered recommended tools are
not assumed called. The same report is written as machine-readable `levers.json` so a chosen set can be applied
in one step later. Nothing is applied by the tuner. `GATE_THRESHOLD` stays 0.8 unless Martin decides; the file
still reports a recommendation for it, marked held, but only when the file has tool labels (`followup.jsonl` skips the per-tool and gate levers). Manual thresholds (`websearch`) are reported as fixed, not proposed. A host run (outside the hub image) needs pydantic and json-repair; the test venv stubs them and ChatRequest will not construct.

