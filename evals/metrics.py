"""Trajectory metrics for one run (batch 7, CHG-010a, S4), read from the run's
own records: its trace files (app/trace, one JSON line per step) and its job
and candidate tables. Nothing is estimated: every number is counted from what
the run wrote.

- ai_calls, schema_failures: `ai.call:<job>` steps and their `validation`
- tool_calls: `agent:<tool>` steps, by tool
- refused: tool calls code refused (unknown tool, bad arguments, a repeat)
- loops: the repeats among them
- tool_errors: tool calls that failed (`result` starts "error:")
- invalid_candidates: candidates that failed their rule checks
- wasted_calls: refused + schema_failures + invalid_candidates
- retries: failed job attempts that were retried; dead_jobs: jobs given up
- escalations: escalation steps that name a rule (stake, max steps, max failures)
- tokens and cost_micro_usd: summed from the `ai.call` steps"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

# The trace fields read here (tests/test_evals.py pins them against app.ai.client and app.agent.loop).
FIELDS = ("tool", "validation", "result", "escalation_rule", "tokens", "cost_micro_usd")


def trace_steps(trace_dir: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for f in sorted(Path(trace_dir).rglob("*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect(steps: list[dict[str, Any]], conn) -> dict[str, Any]:
    ai = [s for s in steps if str(s.get("tool", "")).startswith("ai.call")]
    tools = [s for s in steps if str(s.get("tool", "")).startswith("agent:")]
    refused = [s for s in tools if str(s.get("result") or "").startswith("refused")]
    tokens = Counter()
    for s in ai:
        tokens.update(s.get("tokens") or {})
    (invalid,) = conn.execute("SELECT COUNT(*) FROM candidate WHERE status = 'INVALID'").fetchone()
    # attempts counts failed attempts; every one was retried except a dead job's last
    (failures, dead) = conn.execute("SELECT COALESCE(SUM(attempts), 0), COALESCE(SUM(status = 'dead'), 0) FROM job"
                                    ).fetchone()
    retries = failures - dead
    schema_failures = sum(str(s.get("validation") or "").startswith("schema: failed") for s in ai)
    return {
        "ai_calls": len(ai),
        "ai_calls_by_job": dict(Counter(str(s["tool"]).removeprefix("ai.call:") for s in ai)),
        "schema_failures": schema_failures,
        "tool_calls": len(tools),
        "tool_calls_by_tool": dict(Counter(str(s["tool"]).removeprefix("agent:") for s in tools)),
        "refused": len(refused),
        "loops": sum("repeated call" in str(s.get("result")) for s in refused),
        "tool_errors": sum(str(s.get("result") or "").startswith("error:") for s in tools),
        "invalid_candidates": invalid,
        "wasted_calls": len(refused) + schema_failures + invalid,
        "retries": retries,
        "dead_jobs": dead,
        "escalations": [s["escalation_rule"] for s in steps
                        if s.get("tool") == "escalation" and s.get("escalation_rule")],
        "tokens": {k: tokens.get(k, 0) for k in ("input", "output", "thoughts")},
        "cost_micro_usd": sum(int(s.get("cost_micro_usd") or 0) for s in ai),
    }


def inspect(env) -> dict[str, Any]:
    """The runner's hook: called on the finished run, before its files go."""
    return collect(trace_steps(env.settings.trace_dir), env.conn)
