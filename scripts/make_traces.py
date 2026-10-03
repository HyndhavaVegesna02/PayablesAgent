"""Makes the curated traces in docs/traces/ (batch 7, CHG-010c; Q10):

- success.jsonl: scenario 7, a missed bank alert found by the drift check and
  recovered from the mailbox by the exception agent, on config.yaml as it is;
- failure.jsonl: the same scenario under evals/variants/regress-max-steps.yaml,
  where the agent runs out of steps and code's escalation takes over.

Each is every trace line the run wrote, in the order it was written, one run
per file. The fixture AI makes them deterministic, so tests/test_evidence_docs.py
regenerates them and compares.

    uv run python scripts/make_traces.py            # fixture AI, offline
    uv run python scripts/make_traces.py --check    # exit 1 if docs/traces/ is out of date"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "traces"
SCENARIO = "07-missed-alert-causes-drift"
RUNS = {"success.jsonl": None, "failure.jsonl": ROOT / "evals" / "variants" / "regress-max-steps.yaml"}


def build() -> dict[str, str]:
    from app.ai.fixture_backend import FixtureBackend
    from evals import runner, scenario

    out = {}
    for name, variant in RUNS.items():
        config, _ = runner.load_config(variant)
        with tempfile.TemporaryDirectory(prefix="make-traces-") as tmp_name:
            keep = Path(tmp_name)
            r = runner.run_once(scenario.load(SCENARIO), FixtureBackend(), config, keep=keep)
            failed = [c.id for c in r.checks if not c.ok]
            want = [] if variant is None else ["drift-resolved-in-its-first-run"]
            if r.status != "PASSED" or failed != want:
                raise SystemExit(f"{name}: scenario {SCENARIO} gave {r.status} with failed checks {failed}, "
                                 f"not the {'success' if variant is None else 'path failure'} this trace stands for")
            steps = [json.loads(line) for f in sorted(keep.rglob("*.jsonl"))
                     for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        steps.sort(key=lambda s: (s["timestamp"], int(s["run_id"].split("-")[1]) if s["run_id"].startswith("job-")
                                  else 0, s["run_id"], s["step"]))
        out[name] = "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in steps)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts/make_traces.py")
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    stale = []
    for name, text in build().items():
        path = OUT / name
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT)} ({text.count(chr(10))} lines)")
    if stale:
        print("out of date: " + ", ".join(stale) + " (run: uv run python scripts/make_traces.py)")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
