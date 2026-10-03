"""Escalation (TDD Part 2, "Escalation (escalation.py)"; batch 6, CHG-008,
S5). Code decides, never the model. Each rule has a name, recorded in
agent_case.escalation_rule and in the trace.

- When a case opens: a stake above the business's escalation amount starts it
  at high thinking.
- During a run: 6 steps, or 2 candidates failing their rule checks, ends it.
- After a medium run ends that way: the case reruns at high, steps reset.
- After a high run ends that way: the case goes to the owner."""

from __future__ import annotations

from typing import Literal

STAKE = "stake_above_escalation_amount"
MAX_STEPS = "max_steps"
MAX_FAILURES = "max_validation_failures"


def start_thinking(stake_paise: int, escalation_paise: int) -> tuple[Literal["medium", "high"], str | None]:
    return ("high", STAKE) if stake_paise > escalation_paise else ("medium", None)


def run_over(steps: int, validation_failures: int, *, max_steps: int, max_failures: int) -> str | None:
    """The rule that ends this run, or None while it may go on."""
    if validation_failures >= max_failures:
        return MAX_FAILURES
    if steps >= max_steps:
        return MAX_STEPS
    return None


def after_run(thinking: str) -> Literal["rerun_high", "ask_owner"]:
    return "rerun_high" if thinking == "medium" else "ask_owner"
