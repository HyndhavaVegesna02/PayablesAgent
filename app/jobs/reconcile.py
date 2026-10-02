"""The reconcile_txn, reconcile_failure and drift_check jobs (TDD Part 2,
"Jobs and the document pipeline"). Each runs app.ledger.reconcile and then,
in the same transaction, queues what the result asks for: a replan, the
exception agent's run_case (which waits until CHG-008 registers it), or a
23:00 drift recheck."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from app.jobs import queue
from app.jobs.queue import PermanentJobError
from app.jobs.replan import enqueue_replan
from app.ledger import reconcile, writer

if TYPE_CHECKING:
    from app.worker import JobContext


def _queue_follow_ups(ctx: JobContext, business_id: int, account_id: int | None,
                      result: reconcile.Result) -> None:
    conn = ctx.conn
    if result.replan:
        (last_event,) = conn.execute("SELECT MAX(id) FROM event").fetchone()
        enqueue_replan(conn, business_id, f"event:{last_event}", clock=ctx.clock)
    for case_id in result.case_ids:
        queue.enqueue(conn, kind="run_case", payload={"case_id": case_id},
                      idempotency_key=f"run_case:{case_id}", clock=ctx.clock)
    if result.recheck_at is not None:
        queue.enqueue(conn, kind="drift_check", payload={"account_id": account_id, "source": "recheck"},
                      run_after=result.recheck_at.isoformat(),
                      idempotency_key=f"drift_recheck:{account_id}:{result.recheck_at.date().isoformat()}",
                      clock=ctx.clock)
    ctx.tracer.step(tool="reconcile", result=result.outcome,
                    arguments={"replan": result.replan, "cases": result.case_ids,
                               "recheck_at": result.recheck_at and result.recheck_at.isoformat()})


def _account(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM bank_account WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise PermanentJobError(f"bank_account {account_id} does not exist")
    return row


def handle_reconcile_txn(ctx: JobContext) -> None:
    conn, txn_id = ctx.conn, ctx.payload.get("bank_txn_id")
    txn = conn.execute("SELECT * FROM bank_txn WHERE id = ?", (txn_id,)).fetchone()
    if txn is None:
        raise PermanentJobError(f"bank_txn {txn_id} does not exist")
    acct = _account(conn, txn["account_id"])
    match = reconcile.match_debit if txn["direction"] == "debit" else reconcile.match_credit
    kw = dict(window_days=ctx.app_config.matching.window_days, clock=ctx.clock,
              trace_run_id=ctx.tracer.run_id)
    with writer.atomic(conn):
        _queue_follow_ups(ctx, acct["business_id"], acct["id"], match(conn, txn_id, **kw))
        if _account(conn, acct["id"])["drift_status"] == "CHECKING":
            # Drift check step 5, code side: a transaction found while CHECKING may close the gap.
            closed = reconcile.check_drift(conn, acct["id"], source="new_txn", clock=ctx.clock,
                                           trace_run_id=ctx.tracer.run_id)
            _queue_follow_ups(ctx, acct["business_id"], acct["id"], closed)


def handle_reconcile_failure(ctx: JobContext) -> None:
    conn, candidate_id = ctx.conn, ctx.payload.get("candidate_id")
    row = conn.execute(
        "SELECT d.business_id FROM candidate c JOIN source_document d ON d.id = c.source_document_id "
        "WHERE c.id = ? AND c.status = 'VALID'", (candidate_id,)
    ).fetchone()
    if row is None:
        raise PermanentJobError(f"candidate {candidate_id} is not a valid failure notice")
    with writer.atomic(conn):
        result = reconcile.handle_failure(conn, candidate_id, window_days=ctx.app_config.matching.window_days,
                                          clock=ctx.clock, trace_run_id=ctx.tracer.run_id)
        _queue_follow_ups(ctx, row["business_id"], None, result)


def handle_drift_check(ctx: JobContext) -> None:
    p = ctx.payload
    acct = _account(ctx.conn, p.get("account_id"))
    source = p.get("source")
    if source not in ("alert", "statement", "recheck"):
        raise PermanentJobError(f"unknown drift_check source {source!r}")
    reported_at = datetime.fromisoformat(p["reported_at"]) if p.get("reported_at") else None
    with writer.atomic(ctx.conn):
        result = reconcile.check_drift(ctx.conn, acct["id"], source=source, clock=ctx.clock,
                                       reported_paise=p.get("reported_paise"), reported_at=reported_at,
                                       trace_run_id=ctx.tracer.run_id)
        _queue_follow_ups(ctx, acct["business_id"], acct["id"], result)


def handlers() -> dict:
    return {
        "reconcile_txn": handle_reconcile_txn,
        "reconcile_failure": handle_reconcile_failure,
        "drift_check": handle_drift_check,
    }
