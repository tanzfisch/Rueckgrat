# laya_tune

Tests the scenarios in `dataset.jsonl` with the questions currently in the tools' code. It prints, per tool, how
many examples it got right and a recommended (recommended, mandatory) threshold pair.

```sh
hub/laya_tune/tune.sh
```
Needs the `rueckgrat-hub` image and the laya node (default `192.168.2.158:7346`, change with `LAYA_DECIDE=host:port`).
It uses the code in `hub/app`, so edited questions count without a rebuild.

## dataset.jsonl
One example per line: `{"lang": "en", "text": "Quiz me on capitals", "labels": {"poll": "M"}}`
- `"M"`: the tool should be mandatory. `"r"`: recommended or mandatory are both fine.
- A tool that isn't in `labels` should stay below the recommended threshold.
- Results are printed per `lang`.
