"""The web app's reads (batch 3 plan, CHG-006). Every query takes the
logged-in user's business_id, and an id from a path is looked up within that
business: a miss is NotFound (404), never another business's row.

Nothing here writes. Owner actions are in app/web/actions.py."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.domain.money import format_inr
from app.ledger.reconcile import early_receipt_requests
from app.ledger.writer import calculated_balance
from app.planner.plan import format_day


class NotFound(LookupError):
    """An id that does not exist in the user's business (404)."""


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(conn: sqlite3.Connection, sql: str, args: tuple, what: str) -> dict[str, Any]:
    rows = _rows(conn, sql, args)
    if not rows:
        raise NotFound(f"{what} not found")
    return rows[0]


def _day(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


# --- lookups within the business -----------------------------------------------------


def business(conn: sqlite3.Connection, business_id: int) -> dict[str, Any]:
    return _one(conn, "SELECT * FROM business WHERE id = ?", (business_id,), "business")


def payable(conn: sqlite3.Connection, business_id: int, payable_id: int) -> dict[str, Any]:
    return _one(conn, "SELECT * FROM payable WHERE id = ? AND business_id = ?",
                (payable_id, business_id), f"bill {payable_id}")


def account(conn: sqlite3.Connection, business_id: int, account_id: int) -> dict[str, Any]:
    return _one(conn, "SELECT * FROM bank_account WHERE id = ? AND business_id = ?",
                (account_id, business_id), f"account {account_id}")


def candidate(conn: sqlite3.Connection, business_id: int, candidate_id: int) -> dict[str, Any]:
    return _one(
        conn,
        "SELECT c.*, d.business_id, d.kind AS document_kind, d.submitted_by FROM candidate c "
        "JOIN source_document d ON d.id = c.source_document_id WHERE c.id = ? AND d.business_id = ?",
        (candidate_id, business_id), f"entry {candidate_id}",
    )


def question(conn: sqlite3.Connection, business_id: int, question_id: int) -> dict[str, Any]:
    return _one(conn, "SELECT * FROM owner_question WHERE id = ? AND business_id = ?",
                (question_id, business_id), f"question {question_id}")


def option(conn: sqlite3.Connection, business_id: int, option_id: int) -> dict[str, Any]:
    return _one(
        conn,
        "SELECT o.*, r.is_current, r.business_id FROM shortfall_option o "
        "JOIN plan_run r ON r.id = o.plan_run_id WHERE o.id = ? AND r.business_id = ?",
        (option_id, business_id), f"option {option_id}",
    )


def document(conn: sqlite3.Connection, business_id: int, document_id: int) -> dict[str, Any]:
    return _one(conn, "SELECT * FROM source_document WHERE id = ? AND business_id = ?",
                (document_id, business_id), f"document {document_id}")


def party(conn: sqlite3.Connection, business_id: int, party_id: int) -> dict[str, Any]:
    return _one(conn, "SELECT * FROM party WHERE id = ? AND business_id = ?",
                (party_id, business_id), f"party {party_id}")


def current_run(conn: sqlite3.Connection, business_id: int) -> dict[str, Any] | None:
    rows = _rows(conn, "SELECT * FROM plan_run WHERE business_id = ? AND is_current = 1", (business_id,))
    return rows[0] if rows else None


# --- names shown for bills and parties --------------------------------------------


def bill_names(conn: sqlite3.Connection, business_id: int) -> dict[int, str]:
    """A display name per payable: the vendor, or the taxes a statutory bill
    pays ("PF and ESI"), or its invoice number."""
    names: dict[int, str] = {}
    for r in _rows(
        conn,
        "SELECT p.id, p.invoice_number, pt.name FROM payable p LEFT JOIN party pt ON pt.id = p.party_id "
        "WHERE p.business_id = ?",
        (business_id,),
    ):
        names[r["id"]] = r["name"] or r["invoice_number"] or f"Bill {r['id']}"
    taxes: dict[int, list[str]] = {}
    for r in _rows(
        conn,
        "SELECT payable_id, tax_type FROM tax_obligation WHERE business_id = ? AND payable_id IS NOT NULL "
        "ORDER BY id",
        (business_id,),
    ):
        taxes.setdefault(r["payable_id"], []).append(r["tax_type"])
    for pid, types in taxes.items():
        if pid in names:
            names[pid] = " and ".join(types)
    return names


def receivable_names(conn: sqlite3.Connection, business_id: int) -> dict[int, str]:
    return {
        r["id"]: r["name"] or r["invoice_number"] or f"Invoice {r['id']}"
        for r in _rows(
            conn,
            "SELECT r.id, r.invoice_number, pt.name FROM receivable r "
            "LEFT JOIN party pt ON pt.id = r.party_id WHERE r.business_id = ?",
            (business_id,),
        )
    }


# --- This week --------------------------------------------------------------------


@dataclass
class Line:
    payable_id: int
    name: str
    decision: str
    pay_on: date | None
    amount_paise: int
    reason: str
    status: str
    version: int
    due_date: date


@dataclass
class Day:
    day: date
    balance_paise: int
    below: bool
    pays: list[Line] = field(default_factory=list)


@dataclass
class Option:
    id: int
    kind: str
    label: str
    params: dict[str, Any]
    lowest_balance_paise: int | None
    meets_rule: bool
    chosen: bool
    # CHG-023: an early_receipt the owner already asked the customer for
    pending: str | None = None  # "Chosen on …: waiting for …", shown in place of Choose
    asked_note: str | None = None  # "asked by …; not received", once that date has passed


@dataclass
class PlanView:
    run: dict[str, Any]
    safety_paise: int
    lowest_balance_paise: int
    lowest_on: date
    gap_paise: int  # how far the lowest balance is below the safety amount, else 0
    days: list[Day]
    lines: list[Line]
    waits: list[Line]
    escalations: list[Line]
    next_pay_day: date | None
    to_approve: list[Line]  # PLANNED PAY lines on the next payment day
    options: list[Option]
    authorised: set[int] = field(default_factory=set)  # bills paid under an owner's authorisation (CHG-021)


def plan_view(conn: sqlite3.Connection, business_id: int) -> PlanView | None:
    run = current_run(conn, business_id)
    if run is None:
        return None
    names = bill_names(conn, business_id)
    lines = [
        Line(r["payable_id"], names.get(r["payable_id"], f"Bill {r['payable_id']}"), r["decision"],
             _day(r["pay_on"]), r["amount_paise"], r["reason"], r["status"], r["version"],
             date.fromisoformat(r["due_date"]))
        for r in _rows(
            conn,
            "SELECT pl.payable_id, pl.decision, pl.pay_on, pl.reason, p.amount_paise, p.status, p.version, "
            "p.due_date FROM plan_line pl JOIN payable p ON p.id = pl.payable_id "
            "WHERE pl.plan_run_id = ? ORDER BY pl.pay_on, pl.payable_id",
            (run["id"],),
        )
    ]
    safety = business(conn, business_id)["safety_amount_paise"]
    days = [
        Day(date.fromisoformat(r["day"]), r["balance_paise"], r["balance_paise"] < safety)
        for r in _rows(conn, "SELECT day, balance_paise FROM plan_day WHERE plan_run_id = ? ORDER BY day",
                       (run["id"],))
    ]
    by_day = {d.day: d for d in days}
    for line in lines:
        if line.decision == "PAY" and line.pay_on in by_day:
            by_day[line.pay_on].pays.append(line)
    # Approved bills have no plan line (the planner counts them as fixed
    # outflows on their planned date, or on the first day if that has passed).
    # Bills the owner marked PAID whose debit has not linked yet count the same way (D12).
    paid_unlinked = _rows(conn, "SELECT id, amount_paise, planned_date, status, version FROM payable "
                                "WHERE business_id = ? AND status = 'PAID' AND matched_txn_id IS NULL",
                          (business_id,))
    for b in [*awaiting_payment(conn, business_id), *paid_unlinked]:
        if b["status"] in ("PAYMENT_EXPECTED", "PAID") and days:
            planned = b["planned_date"] if isinstance(b["planned_date"], date) else _day(b["planned_date"])
            on = max(planned or days[0].day, days[0].day)
            if on in by_day:
                by_day[on].pays.append(Line(b["id"], names.get(b["id"], f"Bill {b['id']}"), "PAY", on,
                                            b["amount_paise"], "", b["status"], b["version"], on))
    open_pay = [ln for ln in lines if ln.decision == "PAY" and ln.status == "PLANNED"]
    next_day = min((ln.pay_on for ln in open_pay), default=None)
    lowest = run["lowest_balance_paise"]
    return PlanView(
        run=run, safety_paise=safety, lowest_balance_paise=lowest,
        lowest_on=date.fromisoformat(run["lowest_on"]), gap_paise=max(safety - lowest, 0),
        days=days, lines=lines,
        waits=[ln for ln in lines if ln.decision == "WAIT"],
        escalations=[ln for ln in lines if ln.decision == "ESCALATE"],
        next_pay_day=next_day,
        to_approve=[ln for ln in open_pay if ln.pay_on == next_day],
        options=options(conn, business_id, run["id"]),
        authorised={r[0] for r in conn.execute(
            "SELECT payable_id FROM plan_override WHERE business_id = ? AND kind = 'authorise_breach' "
            "AND status = 'ACTIVE'", (business_id,))},
    )


def awaiting_payment(conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """Approved bills the owner pays in the bank app, and bills a payment
    could not be matched to (REVIEW): the ones mark-paid applies to."""
    names = bill_names(conn, business_id)
    rows = _rows(
        conn,
        "SELECT id, amount_paise, planned_date, status, version FROM payable WHERE business_id = ? "
        "AND status IN ('PAYMENT_EXPECTED', 'REVIEW') ORDER BY planned_date, id",
        (business_id,),
    )
    for r in rows:
        r["name"] = names.get(r["id"], f"Bill {r['id']}")
        r["planned_date"] = _day(r["planned_date"])
    return rows


def option_label(kind: str, params: dict[str, Any], bills: dict[int, str], receivables: dict[int, str]) -> str:
    """The option in Part 1's words, built from its params by code."""
    if kind == "early_receipt":
        who = receivables.get(params["receivable_id"], "the customer")
        return (f"Ask {who} to pay {format_inr(params['amount_paise'])} by "
                f"{format_day(date.fromisoformat(params['to_date']))}")
    if kind == "split":
        who = bills.get(params["payable_id"], "the bill")
        return (f"Split {who}: {format_inr(params['pay_now_paise'])} now, "
                f"{format_inr(params['rest_paise'])} due {format_day(date.fromisoformat(params['rest_due']))}")
    if kind == "delay_flexible":
        who = bills.get(params["payable_id"], "the bill")
        return (f"Pay {who} on {format_day(date.fromisoformat(params['to_date']))} instead of "
                f"{format_day(date.fromisoformat(params['from_date']))}")
    if kind == "authorise_breach":
        return (f"Authorise going below the safety amount ({format_inr(params['gap_paise'])} below "
                f"on {format_day(date.fromisoformat(params['lowest_on']))})")
    return "Ask your CA about the statutory payments"


def options(conn: sqlite3.Connection, business_id: int, run_id: int, today: date | None = None) -> list[Option]:
    bills, receivables = bill_names(conn, business_id), receivable_names(conn, business_id)
    asked: dict[int, tuple[str, str]] = {}  # receivable -> the latest (asked-by date, chosen at)
    for rid, day, chosen_at in early_receipt_requests(conn, business_id):
        asked[rid] = (day, chosen_at)
    open_rx = {r[0] for r in conn.execute(
        "SELECT id FROM receivable WHERE business_id = ? AND confidence <> 'CONFIRMED'", (business_id,))}
    out = []
    for r in _rows(conn, "SELECT * FROM shortfall_option WHERE plan_run_id = ? ORDER BY id", (run_id,)):
        params = json.loads(r["params_json"])
        try:
            label = option_label(r["kind"], params, bills, receivables)
        except (KeyError, TypeError, ValueError):
            label = r["kind"].replace("_", " ")
        option = Option(r["id"], r["kind"], label, params, r["lowest_balance_paise"], bool(r["meets_rule"]),
                        r["chosen_at"] is not None)
        rid = params.get("receivable_id") if r["kind"] == "early_receipt" else None
        if rid in asked and rid in open_rx and today is not None:
            by, chosen_at = asked[rid]
            by_day = date.fromisoformat(by)
            amount = format_inr(params["amount_paise"]) if type(params.get("amount_paise")) is int else ""
            if by_day >= today:
                option.pending = (f"Chosen on {format_day(date.fromisoformat(chosen_at[:10]))}: waiting for "
                                  f"{receivables.get(rid, 'the customer')} to pay {amount} by {format_day(by_day)}")
            else:
                option.asked_note = f"Asked by {format_day(by_day)}; not received"
        out.append(option)
    return out


# --- Needs attention ----------------------------------------------------------------


def active_overrides(conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """The owner's authorisations and delays the planner is honouring now."""
    names = bill_names(conn, business_id)
    rows = _rows(conn, "SELECT * FROM plan_override WHERE business_id = ? AND status = 'ACTIVE' ORDER BY id",
                 (business_id,))
    seen: set[int] = set()
    for r in rows:
        r["name"] = names.get(r["payable_id"], f"Bill {r['payable_id']}")
        r["breach_on"] = _day(r["breach_on"])
        r["created_on"] = date.fromisoformat(r["created_at"][:10])
        # One Undo per choice: undoing it ends every override the choice made.
        r["show_undo"] = r["shortfall_option_id"] not in seen
        seen.add(r["shortfall_option_id"])
    return rows


def debit(conn: sqlite3.Connection, business_id: int, txn_id: int) -> dict[str, Any]:
    return _one(
        conn,
        "SELECT t.* FROM bank_txn t JOIN bank_account a ON a.id = t.account_id "
        "WHERE t.id = ? AND a.business_id = ? AND t.direction = 'debit'",
        (txn_id, business_id), f"debit {txn_id}",
    )


def bills_a_debit_could_pay(conn: sqlite3.Connection, business_id: int, amount_paise: int) -> list[dict[str, Any]]:
    """Open bills a debit could have paid (CHG-022): approved or under review,
    or marked PAID with no debit linked yet. Closest amount first."""
    names = bill_names(conn, business_id)
    rows = _rows(
        conn,
        "SELECT id, party_id, amount_paise, planned_date, status, version FROM payable WHERE business_id = ? "
        "AND (status IN ('PAYMENT_EXPECTED', 'REVIEW') OR (status = 'PAID' AND matched_txn_id IS NULL))",
        (business_id,),
    )
    for r in rows:
        r["name"] = names.get(r["id"], f"Bill {r['id']}")
        r["difference_paise"] = r["amount_paise"] - amount_paise
        r["planned_date"] = _day(r["planned_date"])
    return sorted(rows, key=lambda r: (abs(r["difference_paise"]), r["planned_date"] or date.max, r["id"]))


def open_questions(conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    rows = _rows(conn, "SELECT * FROM owner_question WHERE business_id = ? AND status = 'OPEN' ORDER BY id",
                 (business_id,))
    for r in rows:
        r["choices"] = json.loads(r["choices_json"]) if r["choices_json"] else {}
    return rows


def _with_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for r in rows:
        payload = json.loads(r["payload_json"])
        r["doc_type"] = payload.get("doc_type")
        r["record"] = payload.get("record") or {}
        r["extract"] = payload.get("extract") or {}
        r["checks"] = json.loads(r["checks_json"]) if r["checks_json"] else {}
    return rows


def waiting_candidates(conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """Entries waiting for the owner: typed entries that passed their checks
    (VALID, from a person), and mail candidates the checks could not settle
    (AWAITING_OWNER)."""
    return _with_payload(_rows(
        conn,
        "SELECT c.*, d.kind AS document_kind FROM candidate c JOIN source_document d ON d.id = c.source_document_id "
        "WHERE d.business_id = ? AND (c.status = 'AWAITING_OWNER' "
        "OR (c.status = 'VALID' AND c.created_by LIKE 'user:%')) ORDER BY c.id",
        (business_id,),
    ))


def accounts(conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    rows = _rows(conn, "SELECT * FROM bank_account WHERE business_id = ? ORDER BY id", (business_id,))
    for r in rows:
        r["calculated_paise"] = calculated_balance(conn, r["id"])
    return rows


def accounts_not_ok(conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    return [a for a in accounts(conn, business_id) if a["drift_status"] != "OK"]


# --- Add ----------------------------------------------------------------------------


def submissions(conn: sqlite3.Connection, business_id: int, *, user_id: int | None) -> list[dict[str, Any]]:
    """Documents and typed entries with their status. A helper (user_id set)
    sees only what they submitted; the owner (None) sees everything."""
    sql = (
        "SELECT d.id, d.kind, d.received_at, d.status AS document_status, d.submitted_by, "
        "c.id AS candidate_id, c.record_type, c.status AS candidate_status, c.payload_json "
        "FROM source_document d LEFT JOIN candidate c ON c.source_document_id = d.id "
        "WHERE d.business_id = ? AND d.kind <> 'email'"
    )
    args: list[Any] = [business_id]
    if user_id is not None:
        sql += " AND d.submitted_by = ?"
        args.append(user_id)
    rows = _rows(conn, sql + " ORDER BY d.id DESC", tuple(args))
    for r in rows:
        payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
        r["record"] = payload.get("record") or {}
        r["status_text"] = _submission_status(r)
    return rows


def _submission_status(r: dict[str, Any]) -> str:
    if r["candidate_status"] is None:
        return "Waiting to be read" if r["document_status"] == "NEW" else r["document_status"].capitalize()
    return {
        "VALID": "Waiting for the owner to confirm",
        "AWAITING_OWNER": "Waiting for the owner to confirm",
        "INVALID": "Not accepted: a rule check failed",
        "ACCEPTED": "Confirmed",
        "REJECTED": "Rejected by the owner",
        "NEW": "Waiting to be read",
    }[r["candidate_status"]]


# --- Settings -----------------------------------------------------------------------


def open_bills(conn: sqlite3.Connection, business_id: int) -> list[dict[str, Any]]:
    """Bills whose priority the owner may still change."""
    names = bill_names(conn, business_id)
    rows = _rows(
        conn,
        "SELECT id, amount_paise, due_date, priority, status, version FROM payable WHERE business_id = ? "
        "AND status IN ('DRAFT', 'CONFIRMED', 'PLANNED', 'REOPENED', 'REVIEW') ORDER BY due_date, id",
        (business_id,),
    )
    for r in rows:
        r["name"] = names.get(r["id"], f"Bill {r['id']}")
        r["due_date"] = date.fromisoformat(r["due_date"])
    return rows
