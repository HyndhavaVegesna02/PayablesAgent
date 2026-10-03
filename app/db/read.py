"""Read-only database access. Used by the agent's get_ledger tool so it cannot
write to the ledger even if the rest of the agent code is wrong (TDD Part 2,
"Security in code"), and by the planner's snapshot builder."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app.domain.names import normalise_name
from app.planner.plan import AccountCash, InflowIn, OverrideIn, PayableIn, PlanLine, PlanSnapshot
from app.validate.duplicates import normalise_invoice_number
from app.validate.gstin import normalise_gstin
from app.validate.alert import AccountIn
from app.validate.invoice import InvoiceKey


def read_only_connection(db_path: str | Path) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# --- planner snapshot -------------------------------------------------------------

_DAY_CODES = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_PLANNABLE = ("CONFIRMED", "PLANNED", "REOPENED", "PAYMENT_EXPECTED")


def parse_payment_days(text: str) -> frozenset[int]:
    """'MON,THU' -> {0, 3}. An unknown token is refused, never silently dropped."""
    if text == "":
        return frozenset()
    days = set()
    for token in text.split(","):
        if token not in _DAY_CODES:
            raise ValueError(f"unknown payment day {token!r} in {text!r}")
        days.add(_DAY_CODES[token])
    return frozenset(days)


def _rows(conn: sqlite3.Connection, sql: str, args: tuple) -> list[dict]:
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _date(value: str | None, what: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{what}: not an ISO date: {value!r}") from e


def _planner_status(status: str) -> str:
    """A bill the owner marked PAID whose bank debit has not arrived yet is
    still money leaving the account: the planner sees it exactly as an
    approved payment (PAYMENT_EXPECTED), dated on its planned date or today
    (batch 3 plan, PO decision D12). Once the debit links to it, the debit
    carries the outflow and the bill leaves the snapshot. Known limits: if
    that debit never arrives, the outflow stays committed; while the account
    is CHECKING (opening cash then uses the lower reported balance, which may
    already show the payment) it can be subtracted twice; and a debit that does
    not name-match the bill stays UNMATCHED, so both count (KL-1, D16) until the
    owner's link action (CHG-022). Each errs towards less cash, never more."""
    return "PAYMENT_EXPECTED" if status == "PAID" else status


def build_snapshot(conn: sqlite3.Connection, business_id: int, today: date) -> PlanSnapshot:
    """Reads one business's plannable state into the planner's input. Every
    rule here is a row of the contract grid in docs/batches/2026-10-02-1/plan.md.
    All reads share one read transaction, so a write committed part-way
    through cannot produce a snapshot of a state that never existed."""
    if type(today) is not date:
        raise TypeError("today must be a date (Clock.today()), not a datetime")
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute("BEGIN")
    try:
        return _read_snapshot(conn, business_id, today)
    finally:
        if own_transaction:
            conn.rollback()  # nothing was written; this only ends the read


def _read_snapshot(conn: sqlite3.Connection, business_id: int, today: date) -> PlanSnapshot:
    business = _rows(
        conn, "SELECT safety_amount_paise, horizon_days, payment_days FROM business WHERE id = ?",
        (business_id,),
    )
    if not business:
        raise LookupError(f"business {business_id} does not exist")
    b = business[0]
    if b["horizon_days"] < 1:
        raise ValueError(f"horizon_days must be at least 1, got {b['horizon_days']}")
    horizon_end = today + timedelta(days=b["horizon_days"] - 1)

    accounts = tuple(
        AccountCash(r["id"], r["calculated_balance_paise"], r["reported_balance_paise"],
                    r["drift_status"] != "OK")
        for r in _rows(
            conn,
            "SELECT a.id, ab.calculated_balance_paise, a.reported_balance_paise, a.drift_status "
            "FROM bank_account a JOIN account_balance ab ON ab.account_id = a.id "
            "WHERE a.business_id = ? ORDER BY a.id",
            (business_id,),
        )
    )

    payables = []
    for r in _rows(
        conn,
        "SELECT id, amount_paise, due_date, priority, grace_days, discount_paise, discount_by, "
        f"status, planned_date FROM payable WHERE business_id = ? "
        f"AND (status IN ({','.join('?' for _ in _PLANNABLE)}) "
        "OR (status = 'PAID' AND matched_txn_id IS NULL)) ORDER BY id",
        (business_id, *_PLANNABLE),
    ):
        what = f"payable {r['id']}"
        if r["grace_days"] < 0:
            raise ValueError(f"{what}: negative grace_days")
        discount, discount_by = r["discount_paise"], _date(r["discount_by"], what)
        if discount is not None and not 0 <= discount < r["amount_paise"]:
            raise ValueError(f"{what}: discount_paise must be below the bill amount")
        if not discount or discount_by is None:
            discount, discount_by = None, None
        payables.append(PayableIn(
            payable_id=r["id"], amount_paise=r["amount_paise"], due_date=_date(r["due_date"], what),
            priority=r["priority"], grace_days=r["grace_days"], discount_paise=discount,
            discount_by=discount_by, status=_planner_status(r["status"]),
            planned_date=_date(r["planned_date"], what),
        ))

    inflows, uncounted = [], []
    for r in _rows(
        conn,
        "SELECT id, amount_paise, expected_date, confidence FROM receivable "
        "WHERE business_id = ? AND confidence IN ('COMMITTED', 'EXPECTED') "
        "AND expected_date IS NOT NULL ORDER BY id",
        (business_id,),
    ):
        expected = _date(r["expected_date"], f"receivable {r['id']}")
        inflow = InflowIn(r["id"], r["amount_paise"], expected, r["confidence"])
        if r["confidence"] == "EXPECTED" or expected > horizon_end:
            uncounted.append(inflow)
        elif expected >= today:
            inflows.append(inflow)
        # A COMMITTED date already past with no matched credit is neither counted nor offered.

    planned_ids = {p.payable_id for p in payables}
    overrides = tuple(
        OverrideIn(r["payable_id"], r["kind"], r["floor_paise"], r["shortfall_option_id"])
        for r in _rows(
            conn,
            "SELECT payable_id, kind, floor_paise, shortfall_option_id FROM plan_override WHERE business_id = ? AND status = 'ACTIVE' "
            "ORDER BY id",  # the order chosen: D18 measures each authorisation on the plan the owner saw
            (business_id,),
        )
        if r["payable_id"] in planned_ids
    )

    return PlanSnapshot(
        today=today,
        horizon_days=b["horizon_days"],
        payment_days=parse_payment_days(b["payment_days"]),
        safety_paise=b["safety_amount_paise"],
        accounts=accounts,
        payables=tuple(payables),
        inflows=tuple(inflows),
        commitments=(),  # D1: no commitments table in the MVP
        uncounted_inflows=tuple(uncounted),
        overrides=overrides,
    )


# --- duplicate lookups for the rule checks (pure keys in app/validate/duplicates.py) ---


def bank_txn_with_key(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute("SELECT id FROM bank_txn WHERE dedup_key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def failure_candidate_with_key(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM candidate WHERE status IN ('VALID', 'ACCEPTED') "
        "AND json_extract(payload_json, '$.dedup_key') = ?", (key,)
    ).fetchone()
    return None if row is None else row[0]


# --- invoices: the cross-source duplicate lookup (batch 5 plan, S3) ---------------------


def business_name(conn: sqlite3.Connection, business_id: int) -> str:
    row = conn.execute("SELECT name FROM business WHERE id = ?", (business_id,)).fetchone()
    return row[0] if row else ""


def same_party(a_name: str | None, a_gstin: str | None, b_name: str | None, b_gstin: str | None) -> bool:
    """One GSTIN on each side decides; otherwise the names, as the reconciler
    compares them, either way round (a handwritten bill may drop "Suppliers")."""
    if a_gstin and b_gstin:
        return a_gstin == b_gstin
    a, b = normalise_name(a_name), normalise_name(b_name)
    return bool(a and b) and (a == b or f" {a} " in f" {b} " or f" {b} " in f" {a} ")


def _same_invoice(key: InvoiceKey, name, gstin, number, amount, invoice_date) -> bool:
    if not same_party(key.party, key.party_gstin, name, normalise_gstin(gstin)):
        return False
    n = normalise_invoice_number(number)
    if key.invoice_number and n:
        return key.invoice_number == n
    return (amount == key.amount_paise and key.invoice_date is not None
            and invoice_date == key.invoice_date.isoformat())


def invoice_on_record(conn: sqlite3.Connection, business_id: int, key: InvoiceKey, *,
                      skip_candidate: int | None = None) -> str | None:
    """The same invoice already in the ledger (a bill or a receivable), or
    already waiting for the owner from another source, so an invoice that
    arrives by email, by photo or typed becomes one payable, whichever comes
    first. The one duplicate rule: the pipeline asks it when it reads a
    document, and the confirm form asks it again (skipping the entry being
    confirmed)."""
    for name, gstin, number, amount, day in conn.execute(
        "SELECT pt.name, pt.gstin, t.invoice_number, t.amount_paise, t.invoice_date FROM payable t "
        "JOIN party pt ON pt.id = t.party_id WHERE t.business_id = ? UNION ALL "
        "SELECT pt.name, pt.gstin, t.invoice_number, t.amount_paise, t.invoice_date FROM receivable t "
        "JOIN party pt ON pt.id = t.party_id WHERE t.business_id = ?",
        (business_id, business_id),
    ).fetchall():
        if _same_invoice(key, name, gstin, number, amount, day):
            return f"{name} invoice {number or 'of ' + str(day)} is already recorded"
    for cid, payload_json in conn.execute(
        "SELECT c.id, c.payload_json FROM candidate c JOIN source_document d ON d.id = c.source_document_id "
        "WHERE d.business_id = ? AND c.status IN ('VALID', 'AWAITING_OWNER') "
        "AND c.record_type IN ('payable', 'receivable') ORDER BY c.id",
        (business_id,),
    ).fetchall():
        if cid == skip_candidate:
            continue
        payload = json.loads(payload_json)
        r = payload.get("record") or {}
        if _same_invoice(key, r.get("party"), payload.get("party_gstin"), r.get("invoice_number"),
                         r.get("amount_paise"), r.get("invoice_date")):
            return f"{r.get('party')} invoice {r.get('invoice_number') or 'of ' + str(r.get('invoice_date'))} " \
                   f"is already waiting for the owner (entry {cid})"
    return None


def vendor_party(conn: sqlite3.Connection, business_id: int, name: str | None, gstin: str | None) -> sqlite3.Row | None:
    """The one vendor an invoice names (by GSTIN, or by name either way round),
    or None when there is none or more than one."""
    found = [r for r in conn.execute(
        "SELECT * FROM party WHERE business_id = ? AND kind IN ('vendor', 'both') ORDER BY id", (business_id,)
    ).fetchall() if same_party(name, gstin, r["name"], normalise_gstin(r["gstin"]))]
    return found[0] if len(found) == 1 else None


def statement_with_key(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM candidate WHERE record_type = 'statement' AND status IN ('VALID', 'ACCEPTED') "
        "AND json_extract(payload_json, '$.dedup_key') = ?", (key,)
    ).fetchone()
    return None if row is None else row[0]


def missing_tax_warnings(conn: sqlite3.Connection, business_id: int, today: date, horizon_days: int) -> list[str]:
    """D11: a statutory amount still MISSING and due by the end of the horizon
    (overdue ones too) makes the plan optimistic. Said beside the plan; the
    planner never invents it."""
    end = today + timedelta(days=horizon_days - 1)
    return [
        f"{tax_type} {period} amount missing (due {date.fromisoformat(due).strftime('%a %d %b')}): "
        "plan may be optimistic"
        for tax_type, period, due in conn.execute(
            "SELECT tax_type, period, due_date FROM tax_obligation WHERE business_id = ? "
            "AND amount_status = 'MISSING' AND due_date <= ? ORDER BY due_date, id",
            (business_id, end.isoformat()),
        ).fetchall()
    ]


def what_if_snapshot(conn: sqlite3.Connection, business_id: int, today: date, *,
                     drop_payables: list[int] = (), receivable_dates: dict[int, date] | None = None,
                     safety_paise: int | None = None) -> PlanSnapshot:
    """The current snapshot with what-if changes (POST /api/what-if, and the
    agent's run_planner): bills left out, receivables moved to a date (and
    counted), another safety amount. It only reads. ValueError for a change
    that names nothing open in this business."""
    s = build_snapshot(conn, business_id, today)
    if safety_paise is not None:
        if type(safety_paise) is not int or safety_paise < 0:
            raise ValueError("safety_paise must be int paise, zero or more")
        s = replace(s, safety_paise=safety_paise)
    if any(type(i) is not int for i in drop_payables):
        raise ValueError("drop_payables must be a list of bill ids")
    s = replace(s, payables=tuple(p for p in s.payables if p.payable_id not in set(drop_payables)))
    for rid, when in (receivable_dates or {}).items():
        row = conn.execute("SELECT amount_paise FROM receivable WHERE id = ? AND business_id = ? "
                           "AND confidence IN ('COMMITTED', 'EXPECTED', 'UNKNOWN')", (rid, business_id)).fetchone()
        if row is None:
            raise ValueError(f"receivable {rid} is not open in this business")
        def keep(i, rid=rid):
            return i.receivable_id != rid
        s = replace(s, inflows=tuple(filter(keep, s.inflows)) + (InflowIn(rid, row[0], when, "COMMITTED"),),
                    uncounted_inflows=tuple(filter(keep, s.uncounted_inflows)))
    return s


def accounts_of(conn: sqlite3.Connection, business_id: int) -> list[AccountIn]:
    out = []
    for row in conn.execute(
        "SELECT id, account_mask, alert_senders_json FROM bank_account "
        "WHERE business_id = ? ORDER BY id", (business_id,)
    ):
        try:
            senders = json.loads(row["alert_senders_json"])
        except json.JSONDecodeError:
            senders = []
        out.append(AccountIn(row["id"], row["account_mask"][-4:],
                             frozenset(s.lower() for s in senders if isinstance(s, str))))
    return out


# --- explain_plan (batch 6, CHG-018) ------------------------------------------------------


@dataclass(frozen=True)
class PersistedPlan:
    """A stored plan run, as much of it as diff() reads (planner.diff.PlanFigures)."""

    run_id: int
    opening_cash_paise: int
    lowest_balance_paise: int
    lowest_on: date
    valid: bool
    lines: tuple[PlanLine, ...]


def persisted_result(conn: sqlite3.Connection, run_id: int) -> PersistedPlan:
    """A run rebuilt from plan_run and plan_line. A line's amount is its bill's
    amount now: plan_line keeps no amount, and the planner pays a bill whole."""
    run = conn.execute("SELECT * FROM plan_run WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise LookupError(f"plan_run {run_id} does not exist")
    lines = tuple(
        PlanLine(r["payable_id"], r["decision"], date.fromisoformat(r["pay_on"]) if r["pay_on"] else None,
                 r["amount_paise"], r["reason"])
        for r in conn.execute(
            "SELECT pl.payable_id, pl.decision, pl.pay_on, pl.reason, p.amount_paise FROM plan_line pl "
            "JOIN payable p ON p.id = pl.payable_id WHERE pl.plan_run_id = ? ORDER BY pl.payable_id", (run_id,))
    )
    return PersistedPlan(run["id"], run["opening_cash_paise"], run["lowest_balance_paise"],
                         date.fromisoformat(run["lowest_on"]), bool(run["valid"]), lines)


def bill_names(conn: sqlite3.Connection, business_id: int) -> dict[int, str]:
    """A display name per payable: the vendor, or the taxes a statutory bill
    pays ("PF and ESI"), or its invoice number."""
    names: dict[int, str] = {
        r[0]: r[2] or r[1] or f"Bill {r[0]}"
        for r in conn.execute("SELECT p.id, p.invoice_number, pt.name FROM payable p LEFT JOIN party pt "
                              "ON pt.id = p.party_id WHERE p.business_id = ?", (business_id,))
    }
    taxes: dict[int, list[str]] = {}
    for pid, tax_type in conn.execute(
            "SELECT payable_id, tax_type FROM tax_obligation WHERE business_id = ? AND payable_id IS NOT NULL "
            "ORDER BY id", (business_id,)):
        taxes.setdefault(pid, []).append(tax_type)
    for pid, types in taxes.items():
        if pid in names:
            names[pid] = " and ".join(types)
    return names
