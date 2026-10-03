"""Scoring a run on its scenario's `outcome` checks (batch 7, CHG-010a, S6).

The ablation compares harnesses, so each one is scored the same way, on the
business result alone (D24): rows in the ledger tables of the run's own
database, and the week's plan. The full system's plan is its current
plan_run; the bare harness's (and the no_planner knock-out's) is what the
model said."""

from __future__ import annotations

from typing import Any

from evals.scenario import Outcome, PlanOutcome


def plan_from_db(conn) -> dict[str, Any] | None:
    run = conn.execute("SELECT id, lowest_balance_paise, lowest_on FROM plan_run WHERE is_current = 1").fetchone()
    if run is None:
        return None
    decisions = {pid: f"{decision} {pay_on}" if pay_on and decision == "PAY" else decision
                 for pid, decision, pay_on in conn.execute(
                     "SELECT payable_id, decision, pay_on FROM plan_line WHERE plan_run_id = ?", (run[0],))}
    return {"lowest_paise": run[1], "lowest_on": run[2], "decisions": decisions}


def plan_ok(plan: dict[str, Any] | None, want: PlanOutcome) -> bool:
    if plan is None:
        return False
    if want.lowest_paise is not None and plan.get("lowest_paise") != want.lowest_paise:
        return False
    if want.lowest_on is not None and plan.get("lowest_on") != want.lowest_on:
        return False
    if want.lowest_at_least is not None and (plan.get("lowest_paise") is None
                                             or plan["lowest_paise"] < want.lowest_at_least):
        return False
    got = {int(k): v for k, v in (plan.get("decisions") or {}).items()}
    return all(got.get(pid) == decision for pid, decision in want.decisions.items())


def score(conn, outcomes: list[Outcome], plan: dict[str, Any] | None) -> list[tuple[str, bool, Any]]:
    """(id, ok, what was found) for each outcome check."""
    out = []
    for o in outcomes:
        if o.plan is not None:
            out.append((o.id, plan_ok(plan, o.plan), plan))
        else:
            row = conn.execute(o.sql).fetchone()
            got = row[0] if row else None
            out.append((o.id, got == o.equals, got))
    return out
