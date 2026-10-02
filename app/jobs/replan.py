"""The replan and monday_plan jobs (TDD Part 2, "Jobs and the document
pipeline"; batch 2 plan, CHG-013). One replan reads a snapshot, runs the pure
planner, stores the result as the business's current plan and applies the
planner's state moves through the ledger writer, all in one transaction: a
failure anywhere leaves the previous plan current and no bill moved."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from typing import TYPE_CHECKING

from app.clock import Clock
from app.db.read import build_snapshot
from app.domain.money import format_inr
from app.jobs import queue
from app.ledger import writer
from app.ledger.writer import EntityRef
from app.planner.options import OptionResult, options
from app.planner.plan import (
    PLANNER_VERSION,
    PlanLine,
    PlanResult,
    PlanSnapshot,
    canonical_json,
    format_day,
    plan,
)

if TYPE_CHECKING:
    from app.worker import JobContext

DEFAULT_BUSINESS_ID = 1


def enqueue_replan(
    conn: sqlite3.Connection, business_id: int, triggered_by: str, *, clock: Clock
) -> int:
    """Asks for a replan. A replan still queued for this business absorbs the
    request (it will read the latest ledger when it runs), so a burst of ledger
    changes costs one plan. A running replan does not absorb it: it may have
    read its snapshot before this change."""
    existing = queue.queued_job_id(conn, "replan", business_id)
    if existing is not None:
        return existing
    return queue.enqueue(
        conn, kind="replan", payload={"business_id": business_id, "triggered_by": triggered_by},
        clock=clock,
    )


def handle_replan(ctx: JobContext) -> None:
    replan(
        ctx.conn, ctx.payload.get("business_id", DEFAULT_BUSINESS_ID),
        triggered_by=ctx.payload.get("triggered_by", f"job:{ctx.job['id']}"),
        clock=ctx.clock, trace_run_id=ctx.tracer.run_id,
    )


def handle_monday_plan(ctx: JobContext) -> None:
    # The owner's weekly summary is explain_plan's job (CHG-018).
    replan(
        ctx.conn, ctx.payload.get("business_id", DEFAULT_BUSINESS_ID), triggered_by="monday",
        clock=ctx.clock, trace_run_id=ctx.tracer.run_id,
    )


def replan(
    conn: sqlite3.Connection,
    business_id: int,
    *,
    triggered_by: str,
    clock: Clock,
    trace_run_id: str | None = None,
) -> int:
    """Builds, stores and applies one plan. Returns the new plan_run id."""
    with writer.atomic(conn):
        snapshot = build_snapshot(conn, business_id, clock.today())
        result = plan(snapshot)
        run_id = persist_plan(
            conn, business_id, snapshot, result, options(snapshot, result),
            triggered_by=triggered_by, clock=clock,
        )
        apply_moves(conn, snapshot, result, run_id, clock=clock, trace_run_id=trace_run_id)
    return run_id


def persist_plan(
    conn: sqlite3.Connection,
    business_id: int,
    snapshot: PlanSnapshot,
    result: PlanResult,
    opts: list[OptionResult],
    *,
    triggered_by: str,
    clock: Clock,
) -> int:
    """Stores the plan and makes it the only current one for the business.
    Option what-if plans are not stored as plan lines: they carry synthetic
    payable ids (a split's second part is -payable_id) and are not the plan."""
    conn.execute(
        "UPDATE plan_run SET is_current = 0 WHERE business_id = ? AND is_current = 1",
        (business_id,),
    )
    cur = conn.execute(
        """
        INSERT INTO plan_run (business_id, created_at, triggered_by, inputs_sha256, planner_version,
                              opening_cash_paise, lowest_balance_paise, lowest_on, valid, is_current)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            business_id, clock.now().isoformat(), triggered_by,
            hashlib.sha256(canonical_json(snapshot)).hexdigest(), PLANNER_VERSION,
            result.opening_cash_paise, result.lowest_balance_paise, result.lowest_on.isoformat(),
            int(result.valid),
        ),
    )
    run_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO plan_line (plan_run_id, payable_id, decision, pay_on, reason) VALUES (?, ?, ?, ?, ?)",
        [
            (run_id, ln.payable_id, ln.decision, ln.pay_on and ln.pay_on.isoformat(), ln.reason)
            for ln in result.lines
        ],
    )
    conn.executemany(
        "INSERT INTO plan_day (plan_run_id, day, balance_paise) VALUES (?, ?, ?)",
        [(run_id, d.day.isoformat(), d.balance_paise) for d in result.days],
    )
    conn.executemany(
        "INSERT INTO shortfall_option (plan_run_id, kind, params_json, lowest_balance_paise, meets_rule) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (run_id, o.kind, canonical_json(o.params).decode(), o.lowest_balance_paise, int(o.meets_rule))
            for o in opts
        ],
    )
    return run_id


def paid_balances(result: PlanResult) -> list[tuple[date, int]]:
    """Each day's balance with only the bills this plan pays: the full schedule
    with every ESCALATE bill added back. An escalated bill waits for the
    owner's choice of option, so it is not part of what the plan pays."""
    held = {e.payable_id for e in result.escalations}
    held_moves = [m for m in result.movements if m.source == "bill" and m.ref_id in held]
    return [
        (d.day, d.balance_paise - sum(m.amount_paise for m in held_moves if m.day <= d.day))
        for d in result.days
    ]


def rule_check_text(result: PlanResult, line: PlanLine) -> str:
    """Part 1's example event: the projected minimum from the pay day onward
    (with the bills this plan pays), the safety amount, and whether the rule
    held. It fails only for a statutory bill paid on time through a breach."""
    lowest_on, lowest = min(
        ((d, b) for d, b in paid_balances(result) if d >= line.pay_on), key=lambda x: (x[1], x[0])
    )
    passed = lowest >= result.safety_paise
    return (
        f" Projected minimum {format_inr(lowest)} on {format_day(lowest_on)};"
        f" safety amount {format_inr(result.safety_paise)}; rule check {'PASSED' if passed else 'FAILED'}."
    )


def apply_moves(
    conn: sqlite3.Connection,
    snapshot: PlanSnapshot,
    result: PlanResult,
    run_id: int,
    *,
    clock: Clock,
    trace_run_id: str | None,
) -> None:
    """The planner's state moves (batch 2 plan, CHG-013 state-move table):
    PAY plans a CONFIRMED or REOPENED bill, or moves a PLANNED bill's date;
    WAIT and ESCALATE return a PLANNED bill to CONFIRMED (Q6)."""
    current = {p.payable_id: p for p in snapshot.payables}
    kw = dict(source_ref=f"plan_run:{run_id}", conn=conn, clock=clock, trace_run_id=trace_run_id)
    for line in result.lines:
        bill = current[line.payable_id]
        ref = EntityRef("payable", line.payable_id)
        if line.decision == "PAY":
            reason = line.reason + rule_check_text(result, line)
            if bill.status in ("CONFIRMED", "REOPENED"):
                writer.transition(ref, "PLANNED", "planner", reason,
                                  fields={"planned_date": line.pay_on}, **kw)
            elif bill.status == "PLANNED" and bill.planned_date != line.pay_on:
                writer.set_planned_date(ref, line.pay_on, "planner", reason, **kw)
        elif bill.status == "PLANNED":
            writer.transition(ref, "CONFIRMED", "planner", line.reason, **kw)
