"""One JSON Lines file per run, one line per step (TDD Part 1, "Traces and
audit trail"; Part 2, "Tracing, configuration and security"). Someone who did
not build the agent should be able to explain a failure from the trace alone.

Any field named (or containing) password, token or key is redacted before it
touches disk, recursively through nested dicts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.clock import Clock, SystemClock

REDACTED = "***REDACTED***"
_SENSITIVE_MARKERS = ("password", "token", "key")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and any(m in k.lower() for m in _SENSITIVE_MARKERS):
                out[k] = REDACTED
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class Tracer:
    def __init__(
        self,
        run_id: str,
        trace_dir: str | Path | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.run_id = run_id
        self.trace_dir = Path(trace_dir or os.environ.get("TRACE_DIR", "./traces"))
        self.clock = clock or SystemClock()
        self._step_counter = 0

    def step(self, **fields: Any) -> dict[str, Any]:
        self._step_counter += 1
        entry = {
            "run_id": self.run_id,
            "step": self._step_counter,
            "timestamp": self.clock.now().isoformat(),
            **{k: _redact(v) for k, v in fields.items()},
        }
        day_dir = self.trace_dir / self.clock.today().isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / f"{self.run_id}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
