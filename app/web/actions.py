"""Owner and helper actions behind the web routes (batch 3 plan, CHG-006).

Each action is one transaction. Ledger changes go through app.ledger.writer
as the logged-in owner (actor owner:<id>), and an action that changes what
the plan reads is followed by the inline replan, the same function the
replan job runs (Q2), so the page shows the new plan at once.

Refusals are exceptions the routes turn into plain pages:
- Stale (409): the plan or a bill changed since the page was opened.
- Refused (409): the action does not apply to this record now.
- FieldErrors (422): a form field is missing or unreadable; nothing is stored.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from app.clock import Clock
from app.db.read import bank_txn_with_key, build_snapshot
from app.domain.models import BankTxnNew, PayableNew, ReceivableNew
from app.domain.money import format_inr, parse_inr
from app.jobs import queue
from app.jobs.replan import inputs_sha256, replan
from app.ledger import writer
from app.domain.names import name_matches, normalise_name
from app.ledger.reconcile import party_names
from app.ledger.writer import EntityRef
from app.planner.options import options
from app.planner.plan import InflowIn, canonical_json, effective_snapshot, format_day, plan
from app.validate import CHECK_NAMES, NOT_APPLICABLE, PASSED, failed, failures
from app.ingest import pdf
from app.validate.bank import account_mask, normalise_ifsc
from app.validate.duplicates import txn_dedup_key
from app.web import repo
from app.web.auth import User
from app.web.routes._common import int_or_none

STALE = "The plan changed since you opened it. Here is the current plan."
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PRIORITIES = ("statutory", "critical", "normal", "flexible")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
CONFIDENCES = ("COMMITTED", "EXPECTED", "UNKNOWN")


class Stale(Exception):
    pass


class Refused(Exception):
    pass


class FieldErrors(Exception):
    def __init__(self, errors: dict[str, str], values: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors
        self.values = values


def _replan(conn: sqlite3.Connection, user: User, clock: Clock) -> int:
    (last_event,) = conn.execute("SELECT MAX(id) FROM event WHERE business_id = ?",
                                 (user.business_id,)).fetchone()
    return replan(conn, user.business_id, triggered_by=f"event:{last_event}", clock=clock)


# --- This week: approve and mark paid --------------------------------------------------


def refresh_if_stale(conn: sqlite3.Connection, user: User, *, clock: Clock) -> int | None:
    """After a stale refusal: replans when the current run no longer matches
    today's inputs (the date rolled over, or the ledger changed with no replan
    yet), so the refusal page shows a plan the owner can approve. Returns the
    new run id, or None when the current run is still the right one. The run's
    triggered_by is 'stale-refresh': no event caused it, the date (or an
    unreplanned write) did, so the 'event:<id>' form would name the wrong cause."""
    with writer.atomic(conn):
        current = repo.current_run(conn, user.business_id)
        fresh = inputs_sha256(build_snapshot(conn, user.business_id, clock.today()))
        if current is not None and current["inputs_sha256"] == fresh:
            return None
        return replan(conn, user.business_id, triggered_by="stale-refresh", clock=clock)


def _check_current(conn: sqlite3.Connection, user: User, run_id: int, clock: Clock) -> dict:
    current = repo.current_run(conn, user.business_id)
    if current is None or current["id"] != run_id:
        raise Stale(STALE)
    if inputs_sha256(build_snapshot(conn, user.business_id, clock.today())) != current["inputs_sha256"]:
        raise Stale(STALE)
    return current


def approve(conn: sqlite3.Connection, user: User, run_id: int, versions: dict[int, int], *,
            clock: Clock, bank_checked: frozenset[int] = frozenset()) -> int:
    """Approves the PAY lines for the next payment day (Q4): each moves
    PLANNED -> PAYMENT_EXPECTED with the version the owner saw. Stale (Q3)
    when the run is not current, the inputs it was planned from have changed
    (including the date), or a bill's version moved. A bill to a vendor whose
    bank change is pending needs the owner's tick that he verified the
    details (D20); without it the approval is refused."""
    with writer.atomic(conn):
        _check_current(conn, user, run_id, clock)
        view = repo.plan_view(conn, user.business_id)
        if not view.to_approve:
            raise Refused("There is no payment waiting for approval in this plan.")
        if any(versions.get(ln.payable_id) != ln.version for ln in view.to_approve):
            raise Stale(STALE)
        unticked = [ln.name for ln in view.to_approve
                    if ln.payable_id in view.bank_pending and ln.payable_id not in bank_checked]
        if unticked:
            raise Refused(f"Vendor bank details change pending for {', '.join(unticked)}: verify them with the "
                          "vendor and tick the box before approving.")
        for ln in view.to_approve:
            checked = " (bank details change pending: the owner ticked that he verified them)" \
                if ln.payable_id in view.bank_pending else ""
            writer.transition(
                EntityRef("payable", ln.payable_id), "PAYMENT_EXPECTED", user.actor,
                f"Owner approved paying {ln.name} {format_inr(ln.amount_paise)} on {format_day(ln.pay_on)}{checked}",
                f"plan_run:{run_id}", conn=conn, expected_version=ln.version, clock=clock,
            )
        return _replan(conn, user, clock)


def decide_bank_change(conn: sqlite3.Connection, user: User, party_id: int, candidate_id: int, approve: bool, *,
                       clock: Clock) -> None:
    """POST /parties/{id}/bank-change (owner only): approve copies the new
    details in, from the document that carried them; reject keeps the old
    ones. Either way the vendor's open bank-change questions are answered."""
    with writer.atomic(conn):
        party = repo.party(conn, user.business_id, party_id)
        if party["bank_status"] != "change_pending":
            raise Refused("There is no pending bank change for this vendor.")
        cand = repo.candidate(conn, user.business_id, candidate_id)
        payee = json.loads(cand["payload_json"]).get("payee") or {}
        decision = "approved" if approve else "rejected"
        writer.decide_bank_change(
            party_id, approve, user.actor, f"Owner {decision} the bank change from candidate {candidate_id}",
            f"candidate:{candidate_id}", account_mask=account_mask(payee.get("account")),
            ifsc=normalise_ifsc(payee.get("ifsc")), conn=conn, clock=clock,
        )
        conn.execute(
            "UPDATE owner_question SET status = 'ANSWERED', answer_json = ?, answered_by = ?, answered_at = ? "
            "WHERE business_id = ? AND status = 'OPEN' AND kind = 'approve_bank_change' "
            "AND json_extract(choices_json, '$.party_id') = ?",
            (json.dumps({"decision": decision, "candidate_id": candidate_id}), user.id, clock.now().isoformat(),
             user.business_id, party_id),
        )


class WrongPassword(Exception):
    """The password did not open the PDF. Carries no text: the password never
    goes into a message."""


def unlock_document(conn: sqlite3.Connection, user: User, document_id: int, password: str, store, *,
                    clock: Clock) -> None:
    """POST /documents/{id}/unlock (pipeline step 2): the password opens the
    PDF in memory, once. The unlocked document replaces the locked one in the
    encrypted store and is queued to be read again; the password itself is
    never stored, logged, traced or put in a message (TDD Part 1)."""
    with writer.atomic(conn):
        doc = repo.document(conn, user.business_id, document_id)
        if doc["status"] != "LOCKED":
            raise Refused("There is nothing to unlock: this document is not a locked statement.")
        raw = store.get(doc["storage_path"])
        opened = pdf.unlock(raw, password) if doc["kind"] == "pdf" else pdf.unlock_email(raw, password)
        if opened is None:
            raise WrongPassword()
        store.put(opened, doc["content_sha256"])  # same path: the locked copy is replaced
        conn.execute("UPDATE source_document SET status = 'NEW' WHERE id = ?", (document_id,))
        queue.enqueue(conn, kind="process_document", payload={"document_id": document_id},
                      idempotency_key=f"process_document:{document_id}:unlocked", clock=clock)
        conn.execute(
            "UPDATE owner_question SET status = 'ANSWERED', answer_json = ?, answered_by = ?, answered_at = ? "
            "WHERE business_id = ? AND status = 'OPEN' AND kind = 'unlock_pdf' "
            "AND json_extract(choices_json, '$.document_id') = ?",
            (json.dumps({"decision": "unlocked"}), user.id, clock.now().isoformat(), user.business_id, document_id),
        )


def mark_paid(conn: sqlite3.Connection, user: User, payable_id: int, version: int | None, *,
              clock: Clock) -> int:
    """PAYMENT_EXPECTED or REVIEW -> PAID by the owner (the table refuses any
    other state), with the version from the form."""
    with writer.atomic(conn):
        bill = repo.payable(conn, user.business_id, payable_id)
        if bill["status"] not in ("PAYMENT_EXPECTED", "REVIEW"):
            raise Refused(f"This bill is {bill['status'].replace('_', ' ').lower()}; "
                          "only an approved payment can be marked paid.")
        fields = {}
        txn_id = _reviewed_debit(conn, payable_id) if bill["status"] == "REVIEW" else None
        if txn_id is not None:
            fields["matched_txn_id"] = txn_id
        writer.transition(EntityRef("payable", payable_id), "PAID", user.actor,
                          "Owner marked the payment paid", f"payable:{payable_id}",
                          conn=conn, expected_version=version, fields=fields, clock=clock)
        if txn_id is not None:
            # The owner said this debit paid this bill: the other bills held for it are
            # still expected, and its question is settled (no second link later).
            _release_held(conn, user, txn_id, except_id=payable_id, why="the owner marked another bill paid with it",
                          clock=clock)
            _settle_debit_question(conn, user, txn_id, "Owner marked a bill paid with this debit", clock)
        return _replan(conn, user, clock)


def held_debit(conn: sqlite3.Connection, payable_id: int) -> int | None:
    """The debit a REVIEW bill was held for: its latest PAYABLE_REVIEW event's
    source_ref ("bank_txn:<id>"). The one lookup for mark-paid and explain_txn."""
    row = conn.execute(
        "SELECT source_ref FROM event WHERE entity = 'payable' AND entity_id = ? "
        "AND event_type = 'PAYABLE_REVIEW' ORDER BY id DESC LIMIT 1", (payable_id,),
    ).fetchone()
    if row is None or not (row[0] or "").startswith("bank_txn:"):
        return None
    return int(row[0].removeprefix("bank_txn:"))


def debit_holder(conn: sqlite3.Connection, txn_id: int) -> int | None:
    """The bill a debit already pays, if any (payable.matched_txn_id)."""
    row = conn.execute("SELECT id FROM payable WHERE matched_txn_id = ?", (txn_id,)).fetchone()
    return None if row is None else row[0]


def _reviewed_debit(conn: sqlite3.Connection, payable_id: int) -> int | None:
    """The debit a REVIEW bill was held for, if it is still UNMATCHED and no
    other bill has claimed it. Marking the bill paid says that debit paid it,
    so it is linked and not counted twice (D12): an unlinked PAID bill counts
    as money still to leave. A reversed debit paid nothing."""
    txn_id = held_debit(conn, payable_id)
    if txn_id is None:
        return None
    status = conn.execute("SELECT status FROM bank_txn WHERE id = ?", (txn_id,)).fetchone()
    return txn_id if status is not None and status[0] == "UNMATCHED" and debit_holder(conn, txn_id) is None else None


def _release_held(conn: sqlite3.Connection, user: User, txn_id: int, *, except_id: int | None, why: str,
                  clock: Clock) -> None:
    """REVIEW bills held for this debit that it did not pay go back to expected (Q4)."""
    for (bill_id, bill_version) in conn.execute(
        "SELECT id, version FROM payable WHERE business_id = ? AND status = 'REVIEW' ORDER BY id",
        (user.business_id,),
    ).fetchall():
        if bill_id != except_id and held_debit(conn, bill_id) == txn_id:
            writer.transition(EntityRef("payable", bill_id), "PAYMENT_EXPECTED", user.actor,
                              f"Owner: debit {txn_id} did not pay this bill ({why}); still expected",
                              f"bank_txn:{txn_id}", conn=conn, expected_version=bill_version, clock=clock)


def _settle_debit_question(conn: sqlite3.Connection, user: User, txn_id: int, why: str, clock: Clock) -> None:
    """Closes the open case and answers the open explain_txn question about a
    debit that has been settled another way."""
    for (question_id, case_id) in conn.execute(
        "SELECT id, case_id FROM owner_question WHERE business_id = ? AND kind = 'explain_txn' AND status = 'OPEN' "
        "AND json_extract(choices_json, '$.bank_txn_id') = ?", (user.business_id, txn_id),
    ).fetchall():
        if case_id is not None:
            case = conn.execute("SELECT status FROM agent_case WHERE id = ?", (case_id,)).fetchone()
            if case is not None and case[0] in ("OPEN", "ASK_OWNER"):
                writer.close_case(case_id, user.actor, why, f"bank_txn:{txn_id}", conn=conn, clock=clock)
        _answer(conn, user, question_id, {"decision": "settled", "why": why}, clock)


# --- shortfall options ---------------------------------------------------------------


def choose_option(conn: sqlite3.Connection, user: User, option_id: int, *, clock: Clock) -> int:
    """Records the choice, applies it (Q1), then replans:
    - early_receipt: no ledger change; the owner asks the customer and the
      money counts when it arrives (Part 1, "What happens next").
    - split: split_payable as the owner, with the option's figures.
    - ask_ca: a ca_reminder question.
    - authorise_breach: an override per escalated bill of that plan, bounded
      by the lowest balance the owner saw (CHG-021, D18).
    - delay_flexible: an override for that bill's grace days (CHG-021)."""
    with writer.atomic(conn):
        opt = repo.option(conn, user.business_id, option_id)
        _check_current(conn, user, opt["plan_run_id"], clock)  # the option's figures must still hold
        try:
            params = json.loads(opt["params_json"])
        except ValueError:
            raise Refused("This option can't be applied.") from None
        label = repo.option_label(opt["kind"], params, repo.bill_names(conn, user.business_id),
                                  repo.receivable_names(conn, user.business_id)) \
            if isinstance(params, dict) and _has_params(opt["kind"], params) else None
        if label is None:
            raise Refused("This option can't be applied.")
        source = f"shortfall_option:{option_id}"
        writer.choose_option(option_id, user.actor, f"Owner chose: {label}", source, conn=conn, clock=clock)
        if opt["kind"] == "split":
            bill = repo.payable(conn, user.business_id, params["payable_id"])
            writer.split_payable(
                EntityRef("payable", bill["id"]), params["pay_now_paise"], date.fromisoformat(params["rest_due"]),
                user.actor, f"Owner chose: {label}", source, conn=conn, expected_version=bill["version"],
                clock=clock,
            )
        elif opt["kind"] == "authorise_breach":
            run = conn.execute("SELECT * FROM plan_run WHERE id = ?", (opt["plan_run_id"],)).fetchone()
            for (payable_id,) in conn.execute(
                "SELECT payable_id FROM plan_line WHERE plan_run_id = ? AND decision = 'ESCALATE' ORDER BY payable_id",
                (opt["plan_run_id"],),
            ).fetchall():
                writer.record_override(
                    user.business_id, payable_id, "authorise_breach", user.actor, f"Owner chose: {label}", source,
                    conn=conn, shortfall_option_id=option_id, floor_paise=run["lowest_balance_paise"],
                    breach_on=date.fromisoformat(run["lowest_on"]), clock=clock,
                )
        elif opt["kind"] == "delay_flexible":
            writer.record_override(user.business_id, params["payable_id"], "delay_flexible", user.actor,
                                   f"Owner chose: {label}", source, conn=conn, shortfall_option_id=option_id,
                                   clock=clock)
        elif opt["kind"] == "ask_ca":
            conn.execute(
                "INSERT INTO owner_question (business_id, kind, body_text, choices_json, status) "
                "VALUES (?, 'ca_reminder', ?, ?, 'OPEN')",
                (user.business_id, "Ask your CA whether the statutory payments can wait, and note the answer here.",
                 json.dumps({"option_id": option_id})),
            )
        return _replan(conn, user, clock)


def undo_option(conn: sqlite3.Connection, user: User, option_id: int, *, clock: Clock) -> int:
    """The owner takes back an authorisation or a delay (CHG-021, Q7): its
    overrides end, as the owner, and the plan is made again without them."""
    with writer.atomic(conn):
        repo.option(conn, user.business_id, option_id)  # 404 outside the business
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM plan_override WHERE business_id = ? AND shortfall_option_id = ? AND status = 'ACTIVE'",
            (user.business_id, option_id),
        ).fetchall()]
        if not ids:
            raise Refused("Nothing from this choice is in force any more.")
        for override_id in ids:
            writer.end_override(override_id, "ENDED", user.actor, "Owner undid the choice",
                                f"shortfall_option:{option_id}", conn=conn, clock=clock)
        return _replan(conn, user, clock)


_OPTION_PARAMS = {
    "early_receipt": ("receivable_id", "amount_paise", "to_date"),
    "split": ("payable_id", "pay_now_paise", "rest_paise", "rest_due"),
    "delay_flexible": ("payable_id", "from_date", "to_date"),
    "authorise_breach": ("gap_paise", "lowest_on"),
    "ask_ca": (),
}


def _has_params(kind: str, params: dict[str, Any]) -> bool:
    need = _OPTION_PARAMS.get(kind)
    if need is None or any(k not in params for k in need):
        return False
    try:
        for k in need:
            if k.endswith(("_date", "_due", "_on")):
                date.fromisoformat(params[k])
            elif type(params[k]) is not int:
                return False
    except (TypeError, ValueError):
        return False
    return True


# --- typed entries -------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    kind: str  # "bill" or "invoice"
    record: dict[str, Any]  # JSON-ready: int paise, ISO dates


def _date_field(values: dict[str, str], name: str, errors: dict[str, str], *, required: bool) -> str | None:
    text = (values.get(name) or "").strip()
    if not text:
        if required:
            errors[name] = "Enter a date."
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        errors[name] = "Enter the date as YYYY-MM-DD."
        return None


def parse_entry(values: dict[str, str]) -> Entry:
    """A typed bill or sales invoice from form text. Anything missing or
    unreadable is a field error; nothing is guessed."""
    errors: dict[str, str] = {}
    kind = values.get("kind", "")
    if kind not in ("bill", "invoice"):
        errors["kind"] = "Choose a bill or a sales invoice."
    party = (values.get("party") or "").strip()
    if not party:
        errors["party"] = "Enter who the bill is from (or the invoice is to)."
    amount = None
    try:
        amount = parse_inr(values.get("amount") or "")
        if amount <= 0:
            errors["amount"] = "Enter an amount above zero."
    except ValueError:
        errors["amount"] = "Enter the amount in rupees, like 1,20,000 or Rs.1,20,000."
    record: dict[str, Any] = {
        "party": party, "invoice_number": (values.get("invoice_number") or "").strip() or None,
        "invoice_date": _date_field(values, "invoice_date", errors, required=False), "amount_paise": amount,
    }
    if kind == "bill":
        record["due_date"] = _date_field(values, "due_date", errors, required=True)
        record["priority"] = values.get("priority") or "normal"
        if record["priority"] not in PRIORITIES:
            errors["priority"] = "Choose a priority."
    elif kind == "invoice":
        record["due_date"] = _date_field(values, "due_date", errors, required=False)
        record["expected_date"] = _date_field(values, "expected_date", errors, required=False)
        record["confidence"] = values.get("confidence") or "EXPECTED"
        if record["confidence"] not in CONFIDENCES:
            errors["confidence"] = "Choose how sure the payment is."
    if errors:
        raise FieldErrors(errors, values)
    return Entry(kind, record)


def entry_checks(conn: sqlite3.Connection, business_id: int, entry: Entry, *,
                 skip_candidate: int | None = None) -> dict[str, str]:
    """The rule checks a typed entry goes through (TDD Part 1, "Rule checks"),
    in candidate.checks_json's shape. Fields were parsed already, so schema
    and amount pass; dates and duplicates are real checks here."""
    r = entry.record
    checks = {name: NOT_APPLICABLE for name in CHECK_NAMES}
    checks.update(schema=PASSED, amount=PASSED, dates=PASSED, duplicates=PASSED)
    later = r.get("due_date") or r.get("expected_date")
    if r["invoice_date"] and later and later < r["invoice_date"]:
        checks["dates"] = failed(f"the due date {later} is before the invoice date {r['invoice_date']}")
    table = "payable" if entry.kind == "bill" else "receivable"
    if r["invoice_number"]:
        dup = conn.execute(
            f"SELECT t.id, pt.name FROM {table} t JOIN party pt ON pt.id = t.party_id "
            "WHERE t.business_id = ? AND t.invoice_number = ?",
            (business_id, r["invoice_number"]),
        ).fetchall()
        if any(normalise_name(row[1]) == normalise_name(r["party"]) for row in dup):
            checks["duplicates"] = failed(f"{r['party']} invoice {r['invoice_number']} is already recorded")
    for row in conn.execute(
        "SELECT c.id, c.payload_json FROM candidate c JOIN source_document d ON d.id = c.source_document_id "
        "WHERE d.business_id = ? AND c.status IN ('VALID', 'AWAITING_OWNER') AND c.created_by LIKE 'user:%'",
        (business_id,),
    ).fetchall():
        if row[0] != skip_candidate and json.loads(row[1]).get("record") == {**r, "kind": entry.kind}:
            checks["duplicates"] = failed("the same entry is already waiting for confirmation")
    return checks


def add_entry(conn: sqlite3.Connection, user: User, values: dict[str, str], *, clock: Clock) -> int:
    """POST /entries (Q8): a typed source document plus a candidate waiting
    for the owner. A failed rule check is shown at once, and nothing is stored."""
    entry = parse_entry(values)
    with writer.atomic(conn):
        checks = entry_checks(conn, user.business_id, entry)
        bad = failures(checks)
        if bad:
            raise FieldErrors({"entry": "; ".join(bad.values())}, values)
        record = {**entry.record, "kind": entry.kind}
        now = clock.now().isoformat()
        content = json.dumps({"record": record, "by": user.id, "at": now}, sort_keys=True).encode()
        doc = conn.execute(
            "INSERT INTO source_document (business_id, kind, content_sha256, received_at, submitted_by, status) "
            "VALUES (?, 'typed', ?, ?, ?, 'PROCESSED')",
            (user.business_id, hashlib.sha256(content).hexdigest(), now, user.id),
        ).lastrowid
        return conn.execute(
            "INSERT INTO candidate (source_document_id, record_type, payload_json, checks_json, status, attempts, "
            "created_by, created_at) VALUES (?, ?, ?, ?, 'VALID', 0, ?, ?)",
            (doc, "payable" if entry.kind == "bill" else "receivable",
             json.dumps({"doc_type": "typed", "record": record}, sort_keys=True), json.dumps(checks),
             f"user:{user.id}", now),
        ).lastrowid


_UPLOAD_KINDS = {"application/pdf": "pdf", "image/": "photo", "audio/": "voice"}


def upload_kind(content_type: str | None, filename: str | None) -> str | None:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if not ctype or ctype == "application/octet-stream":
        ctype = mimetypes.guess_type(filename or "")[0] or ""
    for prefix, kind in _UPLOAD_KINDS.items():
        if ctype == prefix or (prefix.endswith("/") and ctype.startswith(prefix)):
            return kind
    return None


def upload(conn: sqlite3.Connection, user: User, content: bytes, kind: str, store, *, clock: Clock) -> int:
    """POST /uploads (Q5): stored encrypted, recorded as a source document and
    queued to be read (CHG-007)."""
    sha = hashlib.sha256(content).hexdigest()
    with writer.atomic(conn):
        seen = conn.execute("SELECT id FROM source_document WHERE business_id = ? AND content_sha256 = ?",
                            (user.business_id, sha)).fetchone()
        if seen is not None:
            raise Refused("This file was already added.")
        doc_id = conn.execute(
            "INSERT INTO source_document (business_id, kind, content_sha256, received_at, submitted_by, "
            "storage_path, status) VALUES (?, ?, ?, ?, ?, ?, 'NEW')",
            (user.business_id, kind, sha, clock.now().isoformat(), user.id, store.put(content, sha)),
        ).lastrowid
        queue.enqueue(conn, kind="process_document", payload={"document_id": doc_id},
                      idempotency_key=f"process_document:{doc_id}", clock=clock)
        return doc_id


# --- confirming and rejecting entries ------------------------------------------------


def _party_id(conn: sqlite3.Connection, business_id: int, name: str, kind: str) -> int:
    """The existing vendor or customer with this name, or a new one."""
    for row in conn.execute("SELECT id, name, kind FROM party WHERE business_id = ? ORDER BY id",
                            (business_id,)).fetchall():
        if normalise_name(row[1]) == normalise_name(name) and row[2] in (kind, "both"):
            return row[0]
    return conn.execute("INSERT INTO party (business_id, kind, name) VALUES (?, ?, ?)",
                        (business_id, kind, name)).lastrowid


def _close_questions(conn: sqlite3.Connection, user: User, candidate_id: int, answer: str, clock: Clock) -> None:
    conn.execute(
        "UPDATE owner_question SET status = 'ANSWERED', answer_json = ?, answered_by = ?, answered_at = ? "
        "WHERE business_id = ? AND status = 'OPEN' AND kind = 'confirm_record' "
        "AND json_extract(choices_json, '$.candidate_id') = ?",
        (json.dumps({"decision": answer}), user.id, clock.now().isoformat(), user.business_id, candidate_id),
    )


def confirm_candidate(conn: sqlite3.Connection, user: User, candidate_id: int, values: dict[str, str], *,
                      clock: Clock) -> int:
    """Accepts an entry with the owner's edits, which go through the same rule
    checks again. A bill becomes CONFIRMED, an invoice a receivable, a bank
    alert an UNMATCHED transaction (Q6) that the reconciler then matches."""
    with writer.atomic(conn):
        cand = repo.candidate(conn, user.business_id, candidate_id)
        if cand["status"] not in ("VALID", "AWAITING_OWNER"):
            raise Refused(f"This entry is already {cand['status'].replace('_', ' ').lower()}.")
        source = f"candidate:{candidate_id}"
        if cand["record_type"] == "txn":
            _confirm_txn(conn, user, cand, values, source, clock)
        elif cand["record_type"] in ("payable", "receivable"):
            values = {**values, "kind": "bill" if cand["record_type"] == "payable" else "invoice"}
            entry = parse_entry(values)
            bad = failures(entry_checks(conn, user.business_id, entry, skip_candidate=candidate_id))
            if bad:
                raise FieldErrors({"entry": "; ".join(bad.values())}, values)
            _create_record(conn, user, cand, entry, source, clock)
        else:
            raise Refused("This kind of entry can't be confirmed here yet.")
        writer.decide_candidate(candidate_id, "ACCEPTED", user.actor, "Owner confirmed the entry", source,
                                conn=conn, clock=clock)
        _close_questions(conn, user, candidate_id, "confirmed", clock)
        return _replan(conn, user, clock)


def _create_record(conn, user: User, cand, entry: Entry, source: str, clock: Clock) -> None:
    r = entry.record
    common = dict(business_id=user.business_id, invoice_number=r["invoice_number"],
                  invoice_date=r["invoice_date"] and date.fromisoformat(r["invoice_date"]),
                  amount_paise=r["amount_paise"], source_document_id=cand["source_document_id"])
    if entry.kind == "bill":
        party_id = _party_id(conn, user.business_id, r["party"], "vendor")
        payee = json.loads(cand["payload_json"]).get("payee") or {}
        writer.record_bank_details(  # a vendor's first details, from the bill the owner checked (S4)
            party_id, account_mask(payee.get("account")), normalise_ifsc(payee.get("ifsc")), user.actor,
            "Bank details from a bill the owner confirmed", source, conn=conn, clock=clock,
        )
        bill = writer.create_payable(
            PayableNew(party_id=party_id,
                       due_date=date.fromisoformat(r["due_date"]), priority=r["priority"], **common),
            actor=user.actor, reason="Owner confirmed a typed bill", source_ref=source, conn=conn, clock=clock,
        )
        writer.transition(EntityRef("payable", bill.id), "CONFIRMED", user.actor, "Owner confirmed the bill",
                          source, conn=conn, expected_version=bill.version, clock=clock)
    else:
        writer.create_receivable(
            ReceivableNew(party_id=_party_id(conn, user.business_id, r["party"], "customer"),
                          due_date=r["due_date"] and date.fromisoformat(r["due_date"]),
                          expected_date=r["expected_date"] and date.fromisoformat(r["expected_date"]),
                          confidence=r["confidence"], **common),
            actor=user.actor, reason="Owner confirmed a typed invoice", source_ref=source, conn=conn, clock=clock,
        )


def _confirm_txn(conn, user: User, cand, values: dict[str, str], source: str, clock: Clock) -> None:
    payload = json.loads(cand["payload_json"])
    if payload.get("doc_type") != "bank_alert":
        raise Refused("Confirming this kind of bank email comes with a later change; reject it or wait.")
    errors: dict[str, str] = {}
    acct = None
    try:
        acct = repo.account(conn, user.business_id, int(values.get("account_id") or 0))
    except (ValueError, repo.NotFound):
        errors["account_id"] = "Choose the account."
    direction = values.get("direction")
    if direction not in ("debit", "credit"):
        errors["direction"] = "Choose money in or money out."
    amount = None
    try:
        amount = parse_inr(values.get("amount") or "")
        if amount <= 0:
            errors["amount"] = "Enter an amount above zero."
    except ValueError:
        errors["amount"] = "Enter the amount in rupees, like 1,20,000."
    txn_date = _date_field(values, "txn_date", errors, required=True)
    if txn_date and txn_date > clock.today().isoformat():
        errors["txn_date"] = "The transaction date can't be in the future."
    if errors:
        raise FieldErrors(errors, values)
    reference = (values.get("reference") or "").strip() or None
    key = txn_dedup_key(acct["id"], date.fromisoformat(txn_date), direction, amount, reference)
    if bank_txn_with_key(conn, key) is not None:
        raise FieldErrors({"entry": "This transaction is already recorded."}, values)
    txn = writer.create_bank_txn(
        BankTxnNew(account_id=acct["id"], direction=direction, amount_paise=amount,
                   txn_date=date.fromisoformat(txn_date),
                   counterparty=(values.get("counterparty") or "").strip() or None, reference=reference,
                   dedup_key=key, source_document_id=cand["source_document_id"], candidate_id=cand["id"],
                   status="UNMATCHED"),
        actor=user.actor, reason="Owner confirmed a bank email the checks could not settle", source_ref=source,
        conn=conn, clock=clock,
    )
    queue.enqueue(conn, kind="reconcile_txn", payload={"bank_txn_id": txn.id},
                  idempotency_key=f"reconcile_txn:{txn.id}", clock=clock)


def reject_candidate(conn: sqlite3.Connection, user: User, candidate_id: int, *, clock: Clock) -> None:
    with writer.atomic(conn):
        cand = repo.candidate(conn, user.business_id, candidate_id)
        if cand["status"] not in ("VALID", "AWAITING_OWNER"):
            raise Refused(f"This entry is already {cand['status'].replace('_', ' ').lower()}.")
        writer.decide_candidate(candidate_id, "REJECTED", user.actor, "Owner rejected the entry",
                                f"candidate:{candidate_id}", conn=conn, clock=clock)
        _close_questions(conn, user, candidate_id, "rejected", clock)


# --- the owner explains a debit (batch 4 plan, CHG-022) -------------------------------


def explain_debit(conn: sqlite3.Connection, user: User, question: dict, values: dict[str, Any], *,
                  clock: Clock) -> int | None:
    """The owner answers an explain_txn question: the debit paid one bill, or
    it was not a bill payment. Linking matches the debit and links or pays the
    bill as the owner, returns the debit's other REVIEW bills to expected,
    optionally adds the payee as a vendor name, closes the case, and replans."""
    choices = json.loads(question["choices_json"] or "{}")
    case_id, txn_id = choices.get("case_id"), choices.get("bank_txn_id")
    if type(case_id) is not int or type(txn_id) is not int:
        raise Refused("This question has no debit to explain.")
    source = f"owner_question:{question['id']}"
    with writer.atomic(conn):
        txn = repo.debit(conn, user.business_id, txn_id)
        holder = debit_holder(conn, txn_id)
        if txn["status"] != "UNMATCHED" or holder is not None:
            # Settled another way meanwhile (matched, reversed, or a bill marked paid
            # with it): the question is closed; a second link would pay two bills.
            why = (f"this debit already pays bill {holder}" if holder is not None
                   else f"this debit is {txn['status'].lower()}")
            _settle_debit_question(conn, user, txn_id, f"Settled: {why}", clock)
            return None
        if values.get("decision") == "not_a_bill":
            _release_held(conn, user, txn_id, except_id=None, why="not a bill payment", clock=clock)
            writer.close_case(case_id, user.actor, "Owner: this debit was not a bill payment", source,
                              conn=conn, clock=clock)
            _answer(conn, user, question["id"], {"decision": "not_a_bill"}, clock)
            return _replan(conn, user, clock)
        bill_id = int_or_none(values.get("payable_id"))
        if bill_id is None:
            raise FieldErrors({"payable_id": "Choose the bill this debit paid."}, values)
        bill = repo.payable(conn, user.business_id, bill_id)
        unlinked_paid = bill["status"] == "PAID" and bill["matched_txn_id"] is None
        if not (unlinked_paid or bill["status"] in ("PAYMENT_EXPECTED", "REVIEW")):
            raise Refused("That bill is not waiting for a payment.")
        version = int_or_none(values.get(f"version_{bill_id}"))
        if version != bill["version"]:
            raise Stale("This bill changed since you opened the page. Reload it and try again.")
        name = repo.bill_names(conn, user.business_id).get(bill_id, f"bill {bill_id}")
        why = f"Owner: this {format_inr(txn['amount_paise'])} debit paid {name}"
        difference = bill["amount_paise"] - txn["amount_paise"]
        if difference:
            why += (f"; debit {format_inr(txn['amount_paise'])} for a {format_inr(bill['amount_paise'])} bill: "
                    f"difference {format_inr(abs(difference))}")
        why += "."
        ref = f"bank_txn:{txn_id}"
        writer.transition(EntityRef("bank_txn", txn_id), "MATCHED", user.actor, why, f"payable:{bill_id}",
                          conn=conn, fields={"party_id": bill["party_id"]}, clock=clock)
        if unlinked_paid:
            writer.link_payment(bill_id, txn_id, user.actor, why, ref, conn=conn, clock=clock)
        else:
            writer.transition(EntityRef("payable", bill_id), "PAID", user.actor, why, ref, conn=conn,
                              expected_version=bill["version"], fields={"matched_txn_id": txn_id}, clock=clock)
        _release_held(conn, user, txn_id, except_id=bill_id, why=f"it paid {name}", clock=clock)
        if values.get("alias") and (txn["counterparty"] or "").strip() and bill["party_id"] is not None \
                and not name_matches(txn["counterparty"], party_names(conn, bill["party_id"])):
            writer.add_party_alias(bill["party_id"], txn["counterparty"], user.actor,
                                   f"Owner: '{txn['counterparty']}' in a bank alert is {name}", source,
                                   conn=conn, clock=clock)
        writer.close_case(case_id, user.actor, why, source, conn=conn, clock=clock)
        _answer(conn, user, question["id"], {"decision": "paid", "payable_id": bill_id}, clock)
        return _replan(conn, user, clock)


def _answer(conn: sqlite3.Connection, user: User, question_id: int, answer: dict, clock: Clock) -> None:
    conn.execute(
        "UPDATE owner_question SET status = 'ANSWERED', answer_json = ?, answered_by = ?, answered_at = ? "
        "WHERE id = ? AND status = 'OPEN'",
        (json.dumps(answer), user.id, clock.now().isoformat(), question_id),
    )


# --- accounts, questions, settings ---------------------------------------------------


def confirm_balance(conn: sqlite3.Connection, user: User, account_id: int, amount_text: str, *,
                    clock: Clock) -> int:
    try:
        real = parse_inr(amount_text or "")
    except ValueError:
        raise FieldErrors({"amount": "Enter the balance in rupees, like 4,12,000."}, {"amount": amount_text}) from None
    with writer.atomic(conn):
        acct = repo.account(conn, user.business_id, account_id)
        if acct["drift_status"] != "ASK_OWNER":
            raise Refused("This account's balance is not waiting for you to confirm.")
        writer.confirm_balance(account_id, real, user.actor, "Owner confirmed the real balance",
                               f"bank_account:{account_id}", conn=conn, clock=clock)
        conn.execute(
            "UPDATE owner_question SET status = 'ANSWERED', answer_json = ?, answered_by = ?, answered_at = ? "
            "WHERE business_id = ? AND status = 'OPEN' AND kind = 'confirm_balance' "
            "AND COALESCE(json_extract(choices_json, '$.account_id'), ?) = ?",
            (json.dumps({"account_id": account_id, "balance_paise": real}), user.id, clock.now().isoformat(),
             user.business_id, account_id, account_id),
        )
        return _replan(conn, user, clock)


def parse_settings(values: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    changes: dict[str, Any] = {}
    for form_name, column in (("safety_amount", "safety_amount_paise"),
                              ("escalation_amount", "escalation_stake_paise")):
        try:
            changes[column] = parse_inr(str(values.get(form_name) or ""))
        except ValueError:
            errors[form_name] = "Enter an amount in rupees, like 2,50,000."
    try:
        changes["horizon_days"] = int(str(values.get("horizon_days") or ""))
        if not 1 <= changes["horizon_days"] <= 60:
            errors["horizon_days"] = "Plan between 1 and 60 days ahead."
    except ValueError:
        errors["horizon_days"] = "Enter a whole number of days."
    days = values.get("payment_days") or []
    days = [days] if isinstance(days, str) else list(days)
    order = WEEKDAYS
    if not days or any(d not in order for d in days):
        errors["payment_days"] = "Choose at least one payment day."
    else:
        changes["payment_days"] = ",".join(d for d in order if d in days)
    if (values.get("language") or "en") != "en":
        errors["language"] = "Only English is available for now."
    changes["language"] = "en"
    if errors:
        raise FieldErrors(errors, {k: v if isinstance(v, str) else ",".join(v) for k, v in values.items()})
    return changes


def update_settings(conn: sqlite3.Connection, user: User, values: dict[str, Any], *, clock: Clock) -> int | None:
    changes = parse_settings(values)
    with writer.atomic(conn):
        after = writer.update_business_settings(user.business_id, changes, user.actor,
                                                "Owner changed the settings", "settings", conn=conn, clock=clock)
        if after is None:
            return None
        return _replan(conn, user, clock)


def set_priority(conn: sqlite3.Connection, user: User, payable_id: int, priority: str, version: int | None, *,
                 clock: Clock) -> int:
    if priority not in PRIORITIES:
        raise FieldErrors({"priority": "Choose a priority."}, {"priority": priority})
    with writer.atomic(conn):
        repo.payable(conn, user.business_id, payable_id)
        writer.set_priority(EntityRef("payable", payable_id), priority, user.actor,
                            f"Owner set the priority to {priority}", "settings", conn=conn,
                            expected_version=version, clock=clock)
        return _replan(conn, user, clock)


# --- what-if (writes nothing) --------------------------------------------------------


def what_if(conn: sqlite3.Connection, user: User, body: dict[str, Any], *, clock: Clock) -> dict[str, Any]:
    """POST /api/what-if (Q9): the planner and its options on the current
    snapshot with the changes in `body`. It writes nothing."""
    if not isinstance(body, dict):
        raise Refused("Send a JSON object.")
    unknown = set(body) - {"receivable_dates", "drop_payables", "safety_paise"}
    if unknown:
        raise Refused(f"Unknown fields: {', '.join(sorted(unknown))}.")
    s = build_snapshot(conn, user.business_id, clock.today())
    try:
        if "safety_paise" in body:
            if type(body["safety_paise"]) is not int or body["safety_paise"] < 0:
                raise ValueError("safety_paise must be int paise, zero or more")
            s = replace(s, safety_paise=body["safety_paise"])
        drop = body.get("drop_payables", [])
        if not isinstance(drop, list) or any(type(i) is not int for i in drop):
            raise ValueError("drop_payables must be a list of bill ids")
        s = replace(s, payables=tuple(p for p in s.payables if p.payable_id not in set(drop)))
        moves = body.get("receivable_dates", {})
        if not isinstance(moves, dict):
            raise ValueError("receivable_dates must map receivable ids to dates")
        for key, day in moves.items():
            rid, when = int(key), date.fromisoformat(day)
            row = conn.execute("SELECT amount_paise FROM receivable WHERE id = ? AND business_id = ? "
                               "AND confidence IN ('COMMITTED', 'EXPECTED', 'UNKNOWN')",
                               (rid, user.business_id)).fetchone()
            if row is None:
                raise ValueError(f"receivable {rid} is not open in this business")
            keep = lambda i: i.receivable_id != rid  # noqa: E731
            s = replace(s, inflows=tuple(filter(keep, s.inflows)) + (InflowIn(rid, row[0], when, "COMMITTED"),),
                        uncounted_inflows=tuple(filter(keep, s.uncounted_inflows)))
    except (TypeError, ValueError) as e:
        raise Refused(str(e)) from None
    result = plan(s)
    s = effective_snapshot(s, result)
    return {
        "plan": json.loads(canonical_json(result)),
        "options": [
            {"kind": o.kind, "params": o.params, "lowest_balance_paise": o.lowest_balance_paise,
             "lowest_on": o.lowest_on and o.lowest_on.isoformat(), "meets_rule": o.meets_rule}
            for o in options(s, result)
        ],
    }
