"""The run_case job (TDD Part 2, "Jobs"; batch 6, CHG-008, S6): runs the
exception agent on one case, then applies its final answer. Applying is code,
here, outside the agent package. Nothing the agent says becomes a state
change by itself:

- RESOLVED is accepted only if it has evidence (at least one cited message,
  or the owner's answer to this case's question), every message it cites
  came from this case's own searches, and every candidate it relies on passed
  its rule checks. An answer with no evidence is not a resolution.
  Otherwise the answer is refused, noted, and counted as a failed check, and
  the run goes on within its limits.
- A relied-on bank alert is written by code, as the pipeline writes a polled
  one (actor `pipeline`), with the case and message as its source (D21).
  reconcile_txn and the drift check follow as usual.
- A drift case is settled by the gap, not by the agent's word (TDD "Drift
  check", step 5): code checks the account again after writing what the agent
  found. The gap closed: CHECKING -> OK and the case is RESOLVED. It did not,
  or the case ends at the owner any other way: the account goes to ASK_OWNER
  and the owner is asked for the real balance (confirm_balance).
- A relied-on bill or invoice goes to the owner to confirm (confirm_record).
- NEEDS_OWNER asks the owner (agent_question).
- There is no path from an answer to approving, paying, marking paid, or
  changing a priority or date."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import TYPE_CHECKING

from app.agent import cases
from app.agent.cases import Case
from app.agent.loop import Deps, ask_agent_question, run_case
from app.ai.agent_step import FinalAnswer
from app.ai.client import AIUnavailable, Backend
from app.db.read import bank_txn_with_key
from app.domain.models import BankTxnNew
from app.ingest.pipeline import _ai_failure, document_store, mail_source
from app.ingest.store import DocumentStore
from app.jobs import queue
from app.jobs.queue import PermanentJobError
from app.jobs.replan import enqueue_replan
from app.ledger import reconcile, writer
from app.ledger.reconcile import RECONCILER

if TYPE_CHECKING:
    from app.worker import Handler, JobContext


def _refuse(conn: sqlite3.Connection, case: Case, why: str, ctx: JobContext) -> bool:
    case.validation_failures += 1
    case.add_note(f"final answer refused by code: {why}")
    cases.save(conn, case, ctx.clock)
    conn.commit()
    ctx.tracer.step(input_ref=f"agent_case:{case.id}", tool="apply_final", validation=f"refused: {why}")
    return False


def _write_alert(conn: sqlite3.Connection, case: Case, cid: int, ctx: JobContext) -> str:
    row = conn.execute("SELECT * FROM candidate WHERE id = ?", (cid,)).fetchone()
    payload = json.loads(row["payload_json"])
    rec = payload["record"]
    if bank_txn_with_key(conn, rec["dedup_key"]) is not None:
        return f"candidate {cid}: already in the ledger"
    message_id = case.state["candidates"][str(cid)]["message_id"]
    # the alert's own time, as the pipeline reports it: an older balance never replaces a newer one
    (received_at,) = conn.execute("SELECT received_at FROM source_document WHERE id = ?",
                                  (row["source_document_id"],)).fetchone()
    txn = writer.create_bank_txn(
        BankTxnNew(account_id=rec["account_id"], direction=rec["direction"], amount_paise=rec["amount_paise"],
                   txn_date=date.fromisoformat(rec["txn_date"]), counterparty=rec["counterparty"],
                   reference=rec["reference"],
                   balance_after_paise=rec["balance_after_paise"], dedup_key=rec["dedup_key"],
                   source_document_id=row["source_document_id"], candidate_id=cid, status="UNMATCHED"),
        actor="pipeline", reason=f"bank alert found by the exception agent, candidate {cid}",
        source_ref=f"agent:case:{case.id} via gmail:{message_id}",  # D21: the audit trail says who found it
        conn=conn, clock=ctx.clock, trace_run_id=ctx.tracer.run_id,
    )
    queue.enqueue(conn, kind="reconcile_txn", payload={"bank_txn_id": txn.id},
                  idempotency_key=f"reconcile_txn:{txn.id}", clock=ctx.clock)
    if rec["balance_after_paise"] is not None:
        queue.enqueue(conn, kind="drift_check",
                      payload={"account_id": rec["account_id"], "source": "alert",
                               "reported_paise": rec["balance_after_paise"], "reported_at": received_at},
                      idempotency_key=f"drift_check:bank_txn:{txn.id}", clock=ctx.clock)
    return f"candidate {cid}: bank_txn {txn.id} written"


def _ask_to_confirm(conn: sqlite3.Connection, case: Case, cid: int, summary: str) -> str:
    conn.execute(
        "INSERT INTO owner_question (business_id, case_id, kind, body_text, choices_json, status) "
        "VALUES (?, ?, 'confirm_record', ?, ?, 'OPEN')",
        (case.business_id, case.id, f"The assistant found this record while working a case: {summary}"[:500],
         json.dumps({"candidate_id": cid})),
    )
    return f"candidate {cid}: the owner confirms it"


def _account_id(case: Case) -> int:
    return int(case.subject_ref.removeprefix("bank_account:"))


def to_owner(conn: sqlite3.Connection, case: Case, question: str, d: Deps, ctx: JobContext) -> None:
    """A case that ends without an answer goes to the owner. A drift case asks
    for the real balance: the account moves CHECKING -> ASK_OWNER (the
    reconciler's step 5 move) and one confirm_balance question opens. Any
    other case asks an agent_question with no choices, which the owner closes."""
    if case.kind != "drift":
        ask_agent_question(conn, case, question, d)
        return
    account_id = _account_id(case)
    with writer.atomic(conn):
        acct = conn.execute("SELECT drift_status, account_mask FROM bank_account WHERE id = ?",
                            (account_id,)).fetchone()
        if acct["drift_status"] == "CHECKING":
            writer.set_drift_status(account_id, "ASK_OWNER", RECONCILER,
                                    f"The assistant could not close the gap (case {case.id}).",
                                    f"agent_case:{case.id}", conn=conn, clock=ctx.clock,
                                    trace_run_id=ctx.tracer.run_id)
        if conn.execute("SELECT 1 FROM owner_question WHERE business_id = ? AND kind = 'confirm_balance' "
                        "AND status = 'OPEN' AND json_extract(choices_json, '$.account_id') = ?",
                        (case.business_id, account_id)).fetchone() is None:
            conn.execute(
                "INSERT INTO owner_question (business_id, case_id, kind, body_text, choices_json, status) "
                "VALUES (?, ?, 'confirm_balance', ?, ?, 'OPEN')",
                (case.business_id, case.id,
                 f"The balance of account {acct['account_mask']} does not match the records, and the assistant "
                 f"could not find why. What is the real balance now? ({question})"[:500],
                 json.dumps({"account_id": account_id, "case_id": case.id})),
            )
        case.status = "ASK_OWNER"


def _settle_drift(conn: sqlite3.Connection, case: Case, d: Deps, ctx: JobContext) -> None:
    """After the agent's findings are written: did they close the gap?"""
    account_id = _account_id(case)
    result = reconcile.check_drift(conn, account_id, source="new_txn", clock=ctx.clock,
                                   trace_run_id=ctx.tracer.run_id)
    status = conn.execute("SELECT drift_status FROM bank_account WHERE id = ?", (account_id,)).fetchone()[0]
    case.add_note(f"drift check after the findings: {result.outcome}")
    if result.replan:
        enqueue_replan(conn, case.business_id, f"agent_case:{case.id}", clock=ctx.clock)
    if status != "OK":
        to_owner(conn, case, "the findings did not close the gap", d, ctx)


def apply_final(conn: sqlite3.Connection, case: Case, final: FinalAnswer, d: Deps, ctx: JobContext) -> bool:
    """True when the answer is applied; False when code refused it."""
    if final.outcome == "NEEDS_OWNER":
        to_owner(conn, case, final.summary, d, ctx)
        case.add_note("the agent passed the case to the owner")
        cases.save(conn, case, ctx.clock)
        conn.commit()
        return True
    if not final.cited_message_ids and not case.state.get("resumed"):
        return _refuse(conn, case, "cites no message this case found", ctx)
    unseen = [m for m in final.cited_message_ids if m not in case.seen_message_ids]
    if unseen:
        return _refuse(conn, case, f"cites messages this case never found: {', '.join(unseen)}", ctx)
    known = case.state.get("candidates", {})
    bad = [c for c in final.relied_on_candidate_ids if known.get(str(c), {}).get("status") != "VALID"]
    if bad:
        return _refuse(conn, case, f"relies on candidates that are not this case's VALID ones: {bad}", ctx)
    with writer.atomic(conn):
        done = []
        for cid in final.relied_on_candidate_ids:
            if known[str(cid)]["record_type"] == "bank_alert":
                done.append(_write_alert(conn, case, cid, ctx))
            else:
                done.append(_ask_to_confirm(conn, case, cid, final.summary))
        case.status = "RESOLVED"
        case.state["summary"] = final.summary
        case.add_note(f"resolved: {final.summary}")
        if case.kind == "drift":
            _settle_drift(conn, case, d, ctx)
        cases.save(conn, case, ctx.clock)
    ctx.tracer.step(input_ref=f"agent_case:{case.id}", tool="apply_final", validation="evidence checked",
                    result="; ".join(done) or "nothing to write")
    return True


def handle_run_case(ctx: JobContext, *, backend: Backend) -> None:
    case_id = ctx.payload.get("case_id")
    if type(case_id) is not int:
        raise PermanentJobError(f"run_case needs an int case_id, got {case_id!r}")
    try:
        store: DocumentStore | None = document_store(ctx.settings)
    except PermanentJobError:
        store = None
    d = Deps(backend, ctx.app_config, ctx.tracer, mail_source(ctx.settings, ctx.clock), ctx.clock,
             ctx.settings.database_path, store)
    d.to_owner = lambda conn, case, question: to_owner(conn, case, question, d, ctx)
    while True:
        try:
            outcome = run_case(ctx.conn, case_id, d)
        except AIUnavailable as e:
            raise _ai_failure(e) from e
        except LookupError as e:
            raise PermanentJobError(str(e)) from None
        if outcome.final is None or apply_final(ctx.conn, outcome.case, outcome.final, d, ctx):
            return


def handlers(backend: Backend) -> dict[str, Handler]:
    import functools

    return {"run_case": functools.partial(handle_run_case, backend=backend)}
