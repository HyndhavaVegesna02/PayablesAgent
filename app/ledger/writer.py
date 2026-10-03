"""The only code that writes ledger tables (payable, receivable, bank_txn,
tax_obligation), changes a bank_account's balance or drift fields, and
writes the event table (TDD Part 2, "Ledger writer"; batch 1 plan, D10).

Every state change goes through transition(); every write records its event
row inside the same SQLite transaction, so a failure anywhere leaves neither.
Actors starting with `agent:` are refused before any SQL runs.
tests/test_ledger_write_guard.py fails if any other module writes these tables."""

from __future__ import annotations

import itertools
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.clock import TIMEZONE, Clock, SystemClock
from app.domain.models import (
    BankTxn,
    BankTxnNew,
    Payable,
    PayableNew,
    Receivable,
    ReceivableNew,
    TaxObligation,
    TaxObligationNew,
)
from app.domain.states import (
    CREATE_RULES,
    DRIFT_TRANSITIONS,
    STATE_COLUMN,
    TRANSITION_FIELDS,
    TRANSITIONS,
    Actor,
    ActorNotAllowed,
    EntityKind,
    FieldNotAllowed,
    FieldRule,
    IllegalTransition,
    RecordNotFound,
    Role,
    StaleVersion,
    VersionRequired,
    parse_actor,
)

_MODELS = {"payable": Payable, "receivable": Receivable, "bank_txn": BankTxn}
_VERSIONED: frozenset[str] = frozenset({"payable", "receivable"})
_savepoints = itertools.count()


@dataclass(frozen=True)
class EntityRef:
    kind: EntityKind
    id: int


# --- plumbing ----------------------------------------------------------------


@contextmanager
def atomic(conn: sqlite3.Connection) -> Iterator[None]:
    """One write transaction. Nested use becomes a savepoint, so callers can
    group several writer calls and have a failure in any of them undo all."""
    if conn.in_transaction:
        name = f"ledger_sp_{next(_savepoints)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def _require_fk(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError(
            "ledger writes need foreign_keys=ON; open the connection with "
            "app.db.connection.write_connection()"
        )


def _fetch(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> dict[str, Any] | None:
    cur = conn.execute(sql, args)
    row = cur.fetchone()
    if row is None:
        return None
    return {d[0]: row[i] for i, d in enumerate(cur.description)}


def _sql_value(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def _insert(conn: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> int:
    cols = list(values)
    cur = conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [_sql_value(values[c]) for c in cols],
    )
    return cur.lastrowid


def _get(conn: sqlite3.Connection, table: str, row_id: int) -> dict[str, Any]:
    row = _fetch(conn, f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    if row is None:
        raise RecordNotFound(f"{table} {row_id} does not exist")
    return row


def _business_of(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> int:
    if table == "bank_txn":
        acct = _fetch(conn, "SELECT business_id FROM bank_account WHERE id = ?", (row["account_id"],))
        if acct is None:
            raise RecordNotFound(f"bank_account {row['account_id']} does not exist")
        return acct["business_id"]
    return row["business_id"]


def _check_role(who: Actor, allowed: frozenset[Role], what: str) -> None:
    if who.role not in allowed:
        raise ActorNotAllowed(f"{who.role} may not {what}")


def _check_owner(conn: sqlite3.Connection, who: Actor, business_id: int) -> None:
    if who.role != "owner":
        return
    user = _fetch(conn, "SELECT role, business_id FROM app_user WHERE id = ?", (who.owner_id,))
    if user is None or user["role"] != "owner" or user["business_id"] != business_id:
        raise ActorNotAllowed(f"user {who.owner_id} is not an owner of business {business_id}")


def _json(row: Mapping[str, Any] | None) -> str | None:
    return None if row is None else json.dumps(dict(row), sort_keys=True)


def _insert_event(
    conn: sqlite3.Connection,
    *,
    business_id: int,
    event_type: str,
    entity: str,
    entity_id: int,
    actor: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    reason: str,
    source_ref: str | None,
    trace_run_id: str | None,
    clock: Clock,
) -> None:
    conn.execute(
        """
        INSERT INTO event (business_id, occurred_at, actor, event_type, entity, entity_id,
                           before_json, after_json, reason, source_ref, trace_run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            business_id, clock.now().isoformat(), actor, event_type, entity, entity_id,
            _json(before), _json(after), reason, source_ref, trace_run_id,
        ),
    )


def _create(
    conn: sqlite3.Connection,
    table: str,
    values: Mapping[str, Any],
    *,
    actor: str,
    reason: str,
    source_ref: str | None,
    trace_run_id: str | None,
    clock: Clock,
) -> dict[str, Any]:
    row_id = _insert(conn, table, values)
    row = _get(conn, table, row_id)
    _insert_event(
        conn, business_id=_business_of(conn, table, row), event_type=f"{table.upper()}_CREATED",
        entity=table, entity_id=row_id, actor=actor, before=None, after=row,
        reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
    )
    return row


# --- creation ----------------------------------------------------------------


def create_payable(
    new: PayableNew,
    *,
    actor: str,
    reason: str,
    source_ref: str | None,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> Payable:
    who = parse_actor(actor)
    _check_role(who, CREATE_RULES["payable"]["DRAFT"], "create a payable")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        _check_owner(conn, who, new.business_id)
        row = _create(
            conn, "payable", {**new.model_dump(), "status": "DRAFT"}, actor=actor,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return Payable.model_validate(row)


def create_receivable(
    new: ReceivableNew,
    *,
    actor: str,
    reason: str,
    source_ref: str | None,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> Receivable:
    who = parse_actor(actor)
    _check_role(who, CREATE_RULES["receivable"][new.confidence], "create a receivable")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        _check_owner(conn, who, new.business_id)
        row = _create(
            conn, "receivable", new.model_dump(), actor=actor,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return Receivable.model_validate(row)


def create_bank_txn(
    new: BankTxnNew,
    *,
    actor: str,
    reason: str,
    source_ref: str | None,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> BankTxn:
    who = parse_actor(actor)
    _check_role(who, CREATE_RULES["bank_txn"][new.status], f"create a {new.status} transaction")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        _check_owner(conn, who, _business_of(conn, "bank_txn", {"account_id": new.account_id}))
        row = _create(
            conn, "bank_txn", new.model_dump(), actor=actor,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return BankTxn.model_validate(row)


def create_tax_obligation(
    new: TaxObligationNew,
    *,
    actor: str,
    reason: str,
    source_ref: str | None,
    conn: sqlite3.Connection,
    payable_id: int | None = None,
    invoice_number: str | None = None,
    payable_amount_paise: int | None = None,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> TaxObligation:
    """Each obligation is backed by a statutory payable (Part 2, "Taxes as payables").
    With payable_id None it creates that payable (DRAFT, amount `payable_amount_paise`
    or the obligation's own); otherwise it links to an existing statutory payable,
    e.g. PF and ESI sharing one combined bill."""
    who = parse_actor(actor)
    _check_role(who, CREATE_RULES["payable"]["DRAFT"], "create a tax obligation")
    if new.amount_status == "MISSING":
        # A payable needs an amount, and the TDD has every obligation create one;
        # how a MISSING amount is tracked is undecided (raised with the PO).
        raise ValueError("a tax obligation with a MISSING amount cannot be recorded yet")
    if payable_amount_paise is not None:
        if payable_id is not None:
            raise ValueError("payable_amount_paise only applies when a new payable is created")
        if type(payable_amount_paise) is not int or payable_amount_paise <= 0:
            raise TypeError("payable_amount_paise must be positive int paise")
    _require_fk(conn)
    clock = clock or SystemClock()
    kw = dict(actor=actor, reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock)
    with atomic(conn):
        _check_owner(conn, who, new.business_id)
        if payable_id is not None:
            linked = _get(conn, "payable", payable_id)
            if linked["priority"] != "statutory" or linked["business_id"] != new.business_id:
                raise ValueError(f"payable {payable_id} is not a statutory payable of this business")
        else:
            payable = _create(
                conn,
                "payable",
                {
                    "business_id": new.business_id,
                    "invoice_number": invoice_number or f"{new.tax_type}-{new.period}",
                    "amount_paise": (
                        new.amount_paise if payable_amount_paise is None else payable_amount_paise
                    ),
                    "due_date": new.due_date,
                    "priority": "statutory",
                    "status": "DRAFT",
                },
                **kw,
            )
            payable_id = payable["id"]
        row = _create(conn, "tax_obligation", {**new.model_dump(), "payable_id": payable_id}, **kw)
    return TaxObligation.model_validate(row)


# --- state changes -----------------------------------------------------------


def _check_fields(kind: EntityKind, to_state: str, fields: Mapping[str, object]) -> None:
    rule = TRANSITION_FIELDS.get((kind, to_state), FieldRule())
    extra = set(fields) - rule.required - rule.optional
    if extra:
        raise FieldNotAllowed(f"{kind} -> {to_state} may not set {sorted(extra)}")
    missing = rule.required - set(fields)
    if missing:
        raise FieldNotAllowed(f"{kind} -> {to_state} requires {sorted(missing)}")
    for name, value in fields.items():
        if name.endswith("_date") and not isinstance(value, date):
            raise TypeError(f"{name} must be a date, got {type(value).__name__}")
        if name.endswith("_id") and value is not None and type(value) is not int:
            raise TypeError(f"{name} must be an int id, got {type(value).__name__}")


def _check_version(kind: str, who: Actor, row: Mapping[str, Any], expected_version: int | None) -> None:
    if kind not in _VERSIONED:
        return  # bank_txn has no version column; the status compare-and-set guards it
    if who.role == "owner" and expected_version is None:
        raise VersionRequired("owner actions must pass the version the owner saw")
    if expected_version is not None and expected_version != row["version"]:
        raise StaleVersion(
            f"{kind} {row['id']} is at version {row['version']}, not {expected_version}"
        )


def _update_state(
    conn: sqlite3.Connection,
    kind: str,
    before: Mapping[str, Any],
    sets: Mapping[str, Any],
) -> None:
    col = STATE_COLUMN[kind]  # type: ignore[index]
    assignments = [f"{c} = ?" for c in sets]
    where = ["id = ?", f"{col} = ?"]
    args = [_sql_value(v) for v in sets.values()]
    where_args: list[Any] = [before["id"], before[col]]
    if kind in _VERSIONED:
        assignments.append("version = version + 1")
        where.append("version = ?")
        where_args.append(before["version"])
    cur = conn.execute(
        f"UPDATE {kind} SET {', '.join(assignments)} WHERE {' AND '.join(where)}",
        args + where_args,
    )
    if cur.rowcount != 1:
        raise StaleVersion(f"{kind} {before['id']} changed underneath this write")


def transition(
    entity: EntityRef,
    to_state: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    expected_version: int | None = None,
    fields: Mapping[str, object] | None = None,
    trace_run_id: str | None = None,
    clock: Clock | None = None,
) -> Payable | Receivable | BankTxn:
    """Move one record to `to_state` if the table allows it for this actor.
    Bumps `version` and writes the event row in the same transaction."""
    who = parse_actor(actor)
    kind = entity.kind
    if kind not in TRANSITIONS:
        raise IllegalTransition(f"{kind} has no state machine")
    if kind == "payable" and to_state == "SPLIT":
        raise IllegalTransition("a split creates two child bills; use split_payable()")
    fields = dict(fields or {})
    _check_fields(kind, to_state, fields)
    _require_fk(conn)
    clock = clock or SystemClock()
    col = STATE_COLUMN[kind]

    with atomic(conn):
        before = _get(conn, kind, entity.id)
        allowed = TRANSITIONS[kind].get((before[col], to_state))
        if allowed is None:
            raise IllegalTransition(f"{kind} {entity.id}: {before[col]} -> {to_state} is not allowed")
        _check_role(who, allowed, f"move {kind} {before[col]} -> {to_state}")
        business_id = _business_of(conn, kind, before)
        _check_owner(conn, who, business_id)
        _check_version(kind, who, before, expected_version)

        sets: dict[str, Any] = {col: to_state, **fields}
        if kind == "payable" and to_state == "PAYMENT_EXPECTED":
            sets["approved_by"] = who.owner_id
            sets["approved_at"] = clock.now().isoformat()
        if kind == "payable" and before[col] == "PLANNED" and to_state == "CONFIRMED":
            sets["planned_date"] = None
        if kind == "payable" and to_state == "REOPENED":
            # The payment failed: the debit it was linked to no longer pays it. A
            # retried bill that the owner marks PAID must count as an outflow again
            # until its new debit links (D12); the old link stays in the event.
            sets["matched_txn_id"] = None
        _update_state(conn, kind, before, sets)
        after = _get(conn, kind, entity.id)
        _insert_event(
            conn, business_id=business_id, event_type=f"{kind.upper()}_{to_state}",
            entity=kind, entity_id=entity.id, actor=actor, before=before, after=after,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
        if kind == "payable" and to_state in ("PAID", "REOPENED"):
            _end_overrides_of(conn, entity.id, to_state, actor, source_ref, trace_run_id, clock)
    return _MODELS[kind].model_validate(after)


def set_planned_date(
    entity: EntityRef,
    planned_date: date,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    expected_version: int | None = None,
    trace_run_id: str | None = None,
    clock: Clock | None = None,
) -> Payable:
    """A replan moves a PLANNED bill to a different pay day. The table has no
    PLANNED -> PLANNED row, so this is its own write (batch 2 plan, Q5):
    planner only, PLANNED only, version bump, PAYABLE_REPLANNED event."""
    who = parse_actor(actor)
    if entity.kind != "payable":
        raise IllegalTransition("only payables have a planned date")
    _check_role(who, frozenset({"planner"}), "move a planned date")
    if type(planned_date) is not date:
        raise TypeError("planned_date must be a date")
    _require_fk(conn)
    clock = clock or SystemClock()

    with atomic(conn):
        before = _get(conn, "payable", entity.id)
        if before["status"] != "PLANNED":
            raise IllegalTransition(f"payable {entity.id} is {before['status']}, not PLANNED")
        if before["planned_date"] == planned_date.isoformat():
            raise IllegalTransition(f"payable {entity.id} is already planned for {planned_date}")
        _check_version("payable", who, before, expected_version)
        _update_state(conn, "payable", before, {"planned_date": planned_date})
        after = _get(conn, "payable", entity.id)
        _insert_event(
            conn, business_id=before["business_id"], event_type="PAYABLE_REPLANNED",
            entity="payable", entity_id=entity.id, actor=actor, before=before, after=after,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return Payable.model_validate(after)


_SPLIT_COPIED = ("business_id", "party_id", "invoice_number", "invoice_date", "priority",
                 "grace_days", "source_document_id")


def split_payable(
    entity: EntityRef,
    first_paise: int,
    second_due_date: date,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    expected_version: int | None,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> tuple[Payable, Payable]:
    """Owner splits a bill: the parent becomes SPLIT and two CONFIRMED children
    carry its amount between them (Part 2, "Splits")."""
    who = parse_actor(actor)
    if entity.kind != "payable":
        raise IllegalTransition("only payables can be split")
    if type(first_paise) is not int:
        raise TypeError("first_paise must be int paise")
    _require_fk(conn)
    clock = clock or SystemClock()

    with atomic(conn):
        before = _get(conn, "payable", entity.id)
        allowed = TRANSITIONS["payable"].get((before["status"], "SPLIT"))
        if allowed is None:
            raise IllegalTransition(f"payable {entity.id}: {before['status']} cannot be split")
        _check_role(who, allowed, "split a bill")
        _check_owner(conn, who, before["business_id"])
        _check_version("payable", who, before, expected_version)
        if not 0 < first_paise < before["amount_paise"]:
            raise ValueError(f"first part must be between 0 and {before['amount_paise']} paise")
        if second_due_date < date.fromisoformat(before["due_date"]):
            raise ValueError("the second part cannot fall due before the original bill")

        _update_state(conn, "payable", before, {"status": "SPLIT"})
        _end_overrides_of(conn, entity.id, "SPLIT", actor, source_ref, trace_run_id, clock)
        after = _get(conn, "payable", entity.id)
        _insert_event(
            conn, business_id=before["business_id"], event_type="PAYABLE_SPLIT", entity="payable",
            entity_id=entity.id, actor=actor, before=before, after=after, reason=reason,
            source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
        copied = {c: before[c] for c in _SPLIT_COPIED}
        children = []
        for amount, due in (
            (first_paise, before["due_date"]),
            (before["amount_paise"] - first_paise, second_due_date),
        ):
            row = _create(
                conn, "payable",
                {**copied, "amount_paise": amount, "due_date": due, "status": "CONFIRMED",
                 "parent_payable_id": entity.id},
                actor=actor, reason=reason, source_ref=f"payable:{entity.id}",
                trace_run_id=trace_run_id, clock=clock,
            )
            children.append(Payable.model_validate(row))
    return children[0], children[1]


def link_payment(
    payable_id: int,
    txn_id: int,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> Payable:
    """The bank debit for a bill the owner already marked PAID has arrived
    (batch 3 plan, PO decision D12): matched_txn_id is set, the version bumps,
    and a PAYABLE_PAYMENT_LINKED event is written. The bill stays PAID; from
    now on the debit, not the bill, carries the outflow. The reconciler links
    a debit that matches; the owner links one that did not (CHG-022)."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"reconciler", "owner"}), "link a payment to a bill")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _get(conn, "payable", payable_id)
        _check_owner(conn, who, before["business_id"])
        txn = _get(conn, "bank_txn", txn_id)
        if before["status"] != "PAID":
            raise IllegalTransition(f"payable {payable_id} is {before['status']}, not PAID")
        if before["matched_txn_id"] is not None:
            raise IllegalTransition(f"payable {payable_id} is already linked to bank_txn {before['matched_txn_id']}")
        if txn["direction"] != "debit" or _business_of(conn, "bank_txn", txn) != before["business_id"]:
            raise IllegalTransition(f"bank_txn {txn_id} is not a debit of this business")
        if txn["status"] == "REVERSED":
            raise IllegalTransition(f"bank_txn {txn_id} was reversed; it paid nothing")
        holder = _fetch(conn, "SELECT id FROM payable WHERE matched_txn_id = ? AND id <> ?", (txn_id, payable_id))
        if holder is not None:
            raise IllegalTransition(f"bank_txn {txn_id} already pays bill {holder['id']}")
        _update_state(conn, "payable", before, {"matched_txn_id": txn_id})
        after = _get(conn, "payable", payable_id)
        _insert_event(
            conn, business_id=before["business_id"], event_type="PAYABLE_PAYMENT_LINKED", entity="payable",
            entity_id=payable_id, actor=actor, before=before, after=after, reason=reason,
            source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return Payable.model_validate(after)


# --- bank accounts: reported balance and drift (batch 2 plan, CHG-005) --------------


def _account(conn: sqlite3.Connection, account_id: int) -> dict[str, Any]:
    return _get(conn, "bank_account", account_id)


def _update_account(conn: sqlite3.Connection, before: Mapping[str, Any], sets: Mapping[str, Any]) -> None:
    """Compare-and-set on drift_status: bank_account has no version column."""
    cur = conn.execute(
        f"UPDATE bank_account SET {', '.join(f'{c} = ?' for c in sets)} WHERE id = ? AND drift_status = ?",
        [*sets.values(), before["id"], before["drift_status"]],
    )
    if cur.rowcount != 1:
        raise StaleVersion(f"bank_account {before['id']} changed underneath this write")


def _account_event(conn, before, after, event_type, *, actor, reason, source_ref, trace_run_id, clock):
    _insert_event(
        conn, business_id=before["business_id"], event_type=event_type, entity="bank_account",
        entity_id=before["id"], actor=actor, before=before, after=after, reason=reason,
        source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
    )


def record_reported_balance(
    account_id: int,
    reported_paise: int,
    reported_at: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    reconciled: bool,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """Stores a balance the bank reported (drift check, step 1). `reconciled`
    means it equals the calculated balance, so last_reconciled_at moves too.
    A report older than the one stored is ignored: the newest one wins. Times
    are compared as instants and stored in Asia/Kolkata, because an email's
    Date header may carry any UTC offset."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"reconciler"}), "record a reported balance")
    if type(reported_paise) is not int:
        raise TypeError("reported_paise must be int paise")
    _require_fk(conn)
    clock = clock or SystemClock()
    at = datetime.fromisoformat(reported_at)
    if at.tzinfo is None:
        raise ValueError("reported_at needs a UTC offset")
    reported_at = at.astimezone(TIMEZONE).isoformat()
    with atomic(conn):
        before = _account(conn, account_id)
        if before["reported_at"] is not None and datetime.fromisoformat(before["reported_at"]) > at:
            return before
        sets: dict[str, Any] = {"reported_balance_paise": reported_paise, "reported_at": reported_at}
        if reconciled:
            sets["last_reconciled_at"] = reported_at
        _update_account(conn, before, sets)
        after = _account(conn, account_id)
        _account_event(conn, before, after, "BANK_ACCOUNT_REPORTED_BALANCE", actor=actor, reason=reason,
                       source_ref=source_ref, trace_run_id=trace_run_id, clock=clock)
    return after


def set_drift_status(
    account_id: int,
    to_status: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """Moves bank_account.drift_status along DRIFT_TRANSITIONS. The owner's
    ASK_OWNER -> OK goes through confirm_balance(), which also writes the
    adjustment, so it is refused here."""
    who = parse_actor(actor)
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _account(conn, account_id)
        allowed = DRIFT_TRANSITIONS.get((before["drift_status"], to_status))
        if allowed is None:
            raise IllegalTransition(
                f"bank_account {account_id}: drift {before['drift_status']} -> {to_status} is not allowed"
            )
        if who.role == "owner":
            raise IllegalTransition("the owner settles drift through confirm_balance()")
        _check_role(who, allowed, f"move drift {before['drift_status']} -> {to_status}")
        _update_account(conn, before, {"drift_status": to_status})
        after = _account(conn, account_id)
        _account_event(conn, before, after, f"BANK_ACCOUNT_{to_status}", actor=actor, reason=reason,
                       source_ref=source_ref, trace_run_id=trace_run_id, clock=clock)
    return after


def calculated_balance(conn: sqlite3.Connection, account_id: int, on_or_before: date | None = None) -> int:
    """Opening balance plus every non-reversed transaction from the opening
    date (up to `on_or_before`, when given): drift check, step 2. With no date
    it is the account_balance view the planner reads; with one it is the same
    rule cut at that day (tests/test_drift.py checks the two agree)."""
    if on_or_before is None:
        row = conn.execute(
            "SELECT calculated_balance_paise FROM account_balance WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise RecordNotFound(f"bank_account {account_id} does not exist")
        return row[0]
    acct = _account(conn, account_id)
    sql = (
        "SELECT COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount_paise ELSE -amount_paise END), 0) "
        "FROM bank_txn WHERE account_id = ? AND status <> 'REVERSED' AND txn_date >= ?"
    )
    args: list[Any] = [account_id, acct["opening_balance_at"], on_or_before.isoformat()]
    sql += " AND txn_date <= ?"
    return acct["opening_balance_paise"] + conn.execute(sql, args).fetchone()[0]


def confirm_balance(
    account_id: int,
    real_paise: int,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> BankTxn | None:
    """The owner answers confirm_balance (drift check, step 6): an ADJUSTMENT
    transaction for the difference, with the owner as actor, and the account
    returns to OK. Returns the adjustment, or None when the owner's figure
    already equals the calculated balance."""
    who = parse_actor(actor)
    _check_role(who, DRIFT_TRANSITIONS[("ASK_OWNER", "OK")], "confirm a balance")
    if type(real_paise) is not int:
        raise TypeError("real_paise must be int paise")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _account(conn, account_id)
        _check_owner(conn, who, before["business_id"])
        if before["drift_status"] != "ASK_OWNER":
            raise IllegalTransition(f"bank_account {account_id} is {before['drift_status']}, not ASK_OWNER")
        gap = real_paise - calculated_balance(conn, account_id)
        now = clock.now().isoformat()
        adjustment = None
        if gap != 0:
            adjustment = create_bank_txn(
                BankTxnNew(account_id=account_id, direction="credit" if gap > 0 else "debit",
                           amount_paise=abs(gap), txn_date=clock.today(),
                           description="Adjustment: the owner confirmed the real balance",
                           dedup_key=f"adjustment:{account_id}:{now}", status="ADJUSTMENT"),
                actor=actor, reason=reason, source_ref=source_ref, conn=conn, clock=clock,
                trace_run_id=trace_run_id,
            )
        _update_account(conn, before, {"drift_status": "OK", "reported_balance_paise": real_paise,
                                       "reported_at": now, "last_reconciled_at": now})
        after = _account(conn, account_id)
        _account_event(conn, before, after, "BANK_ACCOUNT_OK", actor=actor, reason=reason,
                       source_ref=source_ref, trace_run_id=trace_run_id, clock=clock)
    return adjustment


# --- owner settings (batch 3 plan, Q7) ------------------------------------------------

SETTINGS_FIELDS = frozenset({"safety_amount_paise", "escalation_stake_paise", "horizon_days", "payment_days",
                             "language"})
_PAYMENT_DAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _check_settings(changes: Mapping[str, Any]) -> None:
    unknown = set(changes) - SETTINGS_FIELDS
    if unknown:
        raise FieldNotAllowed(f"not a business setting: {sorted(unknown)}")
    for name in ("safety_amount_paise", "escalation_stake_paise"):
        if name in changes and (type(changes[name]) is not int or changes[name] < 0):
            raise ValueError(f"{name} must be int paise, zero or more")
    if "horizon_days" in changes and (type(changes["horizon_days"]) is not int
                                      or not 1 <= changes["horizon_days"] <= 60):
        raise ValueError("horizon_days must be a whole number of days from 1 to 60")
    if "payment_days" in changes:
        days = changes["payment_days"].split(",") if changes["payment_days"] else []
        if not days or any(d not in _PAYMENT_DAY_CODES for d in days) or len(set(days)) != len(days):
            raise ValueError("payment_days must be comma-separated day codes like MON,THU")
    if "language" in changes and changes["language"] not in ("en",):
        raise ValueError("only English is available for now")


def update_business_settings(
    business_id: int,
    changes: Mapping[str, Any],
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any] | None:
    """The owner changes the safety amount, escalation amount, horizon, payment
    days or language. Every change is recorded as an event (TDD "HTTP routes",
    /settings). Returns the new row, or None when nothing changed."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"owner"}), "change the business settings")
    _check_settings(changes)
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        _check_owner(conn, who, business_id)
        before = _get(conn, "business", business_id)
        sets = {k: v for k, v in changes.items() if before[k] != v}
        if not sets:
            return None
        conn.execute(
            f"UPDATE business SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
            [*sets.values(), business_id],
        )
        after = _get(conn, "business", business_id)
        _insert_event(
            conn, business_id=business_id, event_type="BUSINESS_SETTINGS_CHANGED", entity="business",
            entity_id=business_id, actor=actor, before=before, after=after, reason=reason,
            source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return after


_PRIORITY_EDITABLE = frozenset({"DRAFT", "CONFIRMED", "PLANNED", "REOPENED", "REVIEW"})


def set_priority(
    entity: EntityRef,
    priority: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    expected_version: int | None,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> Payable:
    """The owner changes an open bill's priority (statutory, critical, normal,
    flexible), which changes the order the planner places it in."""
    who = parse_actor(actor)
    if entity.kind != "payable":
        raise IllegalTransition("only payables have a priority")
    _check_role(who, frozenset({"owner"}), "change a bill's priority")
    if priority not in ("statutory", "critical", "normal", "flexible"):
        raise ValueError(f"not a priority: {priority!r}")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _get(conn, "payable", entity.id)
        _check_owner(conn, who, before["business_id"])
        _check_version("payable", who, before, expected_version)
        if before["status"] not in _PRIORITY_EDITABLE:
            raise IllegalTransition(f"payable {entity.id} is {before['status']}; its priority is fixed")
        if before["priority"] == priority:
            raise IllegalTransition(f"payable {entity.id} is already {priority}")
        _update_state(conn, "payable", before, {"priority": priority})
        after = _get(conn, "payable", entity.id)
        _insert_event(
            conn, business_id=before["business_id"], event_type="PAYABLE_PRIORITY_CHANGED", entity="payable",
            entity_id=entity.id, actor=actor, before=before, after=after, reason=reason,
            source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return Payable.model_validate(after)


# --- owner decisions outside the ledger tables (batch 3 plan, CHG-006 AC1) ----------
# Choosing a shortfall option and accepting or rejecting an entry change no
# ledger row by themselves, but each is an owner action, so each is an event.


def choose_option(
    option_id: int,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """Records the owner's choice of a shortfall option (chosen_by, chosen_at)
    with a SHORTFALL_OPTION_CHOSEN event. What the choice then does is the
    caller's (app/web/actions.py)."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"owner"}), "choose a shortfall option")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _get(conn, "shortfall_option", option_id)
        run = _get(conn, "plan_run", before["plan_run_id"])
        _check_owner(conn, who, run["business_id"])
        if before["chosen_at"] is not None:
            raise IllegalTransition(f"option {option_id} was already chosen")
        conn.execute(
            "UPDATE shortfall_option SET chosen_by = ?, chosen_at = ? WHERE id = ? AND chosen_at IS NULL",
            (who.owner_id, clock.now().isoformat(), option_id),
        )
        after = _get(conn, "shortfall_option", option_id)
        _insert_event(
            conn, business_id=run["business_id"], event_type="SHORTFALL_OPTION_CHOSEN",
            entity="shortfall_option", entity_id=option_id, actor=actor, before=before, after=after,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return after


_CANDIDATE_DECISIONS = {
    ("VALID", "ACCEPTED"), ("VALID", "REJECTED"),
    ("AWAITING_OWNER", "ACCEPTED"), ("AWAITING_OWNER", "REJECTED"),
}


def decide_candidate(
    candidate_id: int,
    to_status: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """The owner accepts (after creating its record) or rejects an entry
    waiting for confirmation: CANDIDATE_ACCEPTED or CANDIDATE_REJECTED."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"owner"}), "accept or reject an entry")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _get(conn, "candidate", candidate_id)
        business_id = _get(conn, "source_document", before["source_document_id"])["business_id"]
        _check_owner(conn, who, business_id)
        if (before["status"], to_status) not in _CANDIDATE_DECISIONS:
            raise IllegalTransition(f"entry {candidate_id}: {before['status']} -> {to_status} is not allowed")
        cur = conn.execute("UPDATE candidate SET status = ? WHERE id = ? AND status = ?",
                           (to_status, candidate_id, before["status"]))
        if cur.rowcount != 1:
            raise StaleVersion(f"entry {candidate_id} changed underneath this write")
        after = _get(conn, "candidate", candidate_id)
        _insert_event(
            conn, business_id=business_id, event_type=f"CANDIDATE_{to_status}", entity="candidate",
            entity_id=candidate_id, actor=actor, before=before, after=after, reason=reason,
            source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return after


# --- the owner explains a debit (batch 4 plan, CHG-022) -----------------------------


def add_party_alias(
    party_id: int,
    alias: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """The owner confirms that a name seen in a bank alert is this vendor
    (TDD: aliases are "added only after owner confirms"). Owner only; a
    PARTY_ALIAS_ADDED event. Adding a name already there changes nothing."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"owner"}), "add a vendor name")
    alias = " ".join(alias.split())
    if not alias:
        raise ValueError("an alias needs some text")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _get(conn, "party", party_id)
        _check_owner(conn, who, before["business_id"])
        try:
            aliases = json.loads(before["aliases_json"] or "[]")
        except json.JSONDecodeError:
            raise IllegalTransition(f"party {party_id} has an unreadable alias list") from None
        if not isinstance(aliases, list):
            raise IllegalTransition(f"party {party_id} has an unreadable alias list")
        if alias in aliases:
            return before
        conn.execute("UPDATE party SET aliases_json = ? WHERE id = ?", (json.dumps([*aliases, alias]), party_id))
        after = _get(conn, "party", party_id)
        _insert_event(
            conn, business_id=before["business_id"], event_type="PARTY_ALIAS_ADDED", entity="party",
            entity_id=party_id, actor=actor, before=before, after=after, reason=reason,
            source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return after


def close_case(
    case_id: int,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """The owner settles an exception case (CLOSED_BY_OWNER), with an event."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"owner"}), "close a case")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _get(conn, "agent_case", case_id)
        _check_owner(conn, who, before["business_id"])
        if before["status"] not in ("OPEN", "ASK_OWNER"):
            raise IllegalTransition(f"case {case_id} is {before['status']}")
        conn.execute("UPDATE agent_case SET status = 'CLOSED_BY_OWNER', updated_at = ? WHERE id = ?",
                     (clock.now().isoformat(), case_id))
        after = _get(conn, "agent_case", case_id)
        _insert_event(
            conn, business_id=before["business_id"], event_type="AGENT_CASE_CLOSED_BY_OWNER", entity="agent_case",
            entity_id=case_id, actor=actor, before=before, after=after, reason=reason,
            source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return after


# --- planner overrides (batch 4 plan, CHG-021; PO decisions D17, D18) ---------------

OVERRIDE_KINDS = frozenset({"authorise_breach", "delay_flexible"})


def record_override(
    business_id: int,
    payable_id: int,
    kind: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    shortfall_option_id: int | None = None,
    floor_paise: int | None = None,
    breach_on: date | None = None,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """The owner tells the planner to pay an escalated bill below the safety
    amount, down to the floor he saw (authorise_breach, D18), or to use a
    flexible bill's grace days (delay_flexible). Owner only; one ACTIVE
    override per bill and kind (a repeat returns the one in force)."""
    who = parse_actor(actor)
    _check_role(who, frozenset({"owner"}), "record a planner override")
    if kind not in OVERRIDE_KINDS:
        raise ValueError(f"not an override kind: {kind!r}")
    if kind == "authorise_breach" and type(floor_paise) is not int:
        raise ValueError("an authorisation records the floor the owner saw, in int paise")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        _check_owner(conn, who, business_id)
        bill = _get(conn, "payable", payable_id)
        if bill["business_id"] != business_id:
            raise RecordNotFound(f"payable {payable_id} is not in business {business_id}")
        if bill["status"] not in ("CONFIRMED", "PLANNED", "REOPENED"):
            raise IllegalTransition(f"payable {payable_id} is {bill['status']}; it is not waiting to be planned")
        existing = _fetch(conn, "SELECT * FROM plan_override WHERE payable_id = ? AND kind = ? AND status = 'ACTIVE'",
                          (payable_id, kind))
        if existing is not None:
            return existing
        row = _create_row(conn, "plan_override", {
            "business_id": business_id, "payable_id": payable_id, "kind": kind,
            "shortfall_option_id": shortfall_option_id, "floor_paise": floor_paise,
            "breach_on": breach_on, "created_by": who.owner_id, "created_at": clock.now().isoformat(),
            "status": "ACTIVE",
        })
        _insert_event(
            conn, business_id=business_id, event_type="PLAN_OVERRIDE_RECORDED", entity="plan_override",
            entity_id=row["id"], actor=actor, before=None, after=row, reason=reason, source_ref=source_ref,
            trace_run_id=trace_run_id, clock=clock,
        )
    return row


def _create_row(conn: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> dict[str, Any]:
    return _get(conn, table, _insert(conn, table, values))


def end_override(
    override_id: int,
    to_status: str,
    actor: str,
    reason: str,
    source_ref: str | None,
    *,
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    trace_run_id: str | None = None,
) -> dict[str, Any]:
    """ENDED: the owner undid it, or its bill left the plan (paid, split,
    reopened). LAPSED: the planner found the breach deeper than the floor the
    owner authorised (D18); the row stays, inactive. Each with an event."""
    who = parse_actor(actor)
    allowed = {"ENDED": frozenset({"owner", "reconciler", "planner"}), "LAPSED": frozenset({"planner"})}
    if to_status not in allowed:
        raise IllegalTransition(f"an override cannot move to {to_status}")
    _check_role(who, allowed[to_status], f"move an override to {to_status}")
    _require_fk(conn)
    clock = clock or SystemClock()
    with atomic(conn):
        before = _get(conn, "plan_override", override_id)
        _check_owner(conn, who, before["business_id"])
        if before["status"] != "ACTIVE":
            raise IllegalTransition(f"override {override_id} is {before['status']}")
        conn.execute("UPDATE plan_override SET status = ?, ended_at = ? WHERE id = ? AND status = 'ACTIVE'",
                     (to_status, clock.now().isoformat(), override_id))
        after = _get(conn, "plan_override", override_id)
        _insert_event(
            conn, business_id=before["business_id"], event_type=f"PLAN_OVERRIDE_{to_status}",
            entity="plan_override", entity_id=override_id, actor=actor, before=before, after=after,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
    return after


def _end_overrides_of(conn: sqlite3.Connection, payable_id: int, to_state: str, actor: str,
                      source_ref: str | None, trace_run_id: str | None, clock: Clock) -> None:
    """A bill that is paid, split or reopened leaves the plan, and so do its
    overrides, in the same transaction as its move (CHG-021, Q7)."""
    for (override_id,) in conn.execute(
        "SELECT id FROM plan_override WHERE payable_id = ? AND status = 'ACTIVE'", (payable_id,)
    ).fetchall():
        end_override(override_id, "ENDED", actor,
                     f"the bill moved to {to_state}", source_ref, conn=conn, clock=clock, trace_run_id=trace_run_id)
