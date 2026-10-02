"""`python -m app.trace.view <run_id>` — prints a run as readable steps."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def find_run_file(trace_dir: str | Path, run_id: str) -> Path | None:
    trace_dir = Path(trace_dir)
    matches = sorted(trace_dir.glob(f"*/{run_id}.jsonl"))
    return matches[-1] if matches else None


def format_step(entry: dict) -> str:
    parts = [f"step {entry.get('step')}", f"@ {entry.get('timestamp')}"]
    if entry.get("tool"):
        parts.append(f"tool={entry['tool']}")
    if entry.get("model"):
        parts.append(f"model={entry['model']}({entry.get('thinking')})")
    if entry.get("result") is not None:
        parts.append(f"result={entry['result']}")
    if entry.get("validation"):
        parts.append(f"validation={entry['validation']}")
    if entry.get("tokens"):
        t = entry["tokens"]
        parts.append("tokens=" + "/".join(f"{k}:{t[k]}" for k in ("input", "output", "thoughts") if k in t))
    if entry.get("cost_micro_usd") is not None:
        parts.append(f"cost={entry['cost_micro_usd']}µ$")
    if entry.get("retries"):
        parts.append(f"retries={entry['retries']}")
    if entry.get("escalation_rule"):
        parts.append(f"escalation_rule={entry['escalation_rule']}")
    return " ".join(str(p) for p in parts)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m app.trace.view <run_id>", file=sys.stderr)
        return 2
    run_id = argv[0]
    trace_dir = os.environ.get("TRACE_DIR", "./traces")
    path = find_run_file(trace_dir, run_id)
    if path is None:
        print(f"no trace found for run_id={run_id} under {trace_dir}", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            print(format_step(json.loads(line)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
