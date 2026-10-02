"""The only code that writes ledger tables (payable, receivable, bank_txn,
tax_obligation) and the event table (TDD Part 2, "Ledger writer").

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
from datetime import date
from typing import Any

from app.clock import Clock, SystemClock
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
        _update_state(conn, kind, before, sets)
        after = _get(conn, kind, entity.id)
        _insert_event(
            conn, business_id=business_id, event_type=f"{kind.upper()}_{to_state}",
            entity=kind, entity_id=entity.id, actor=actor, before=before, after=after,
            reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock,
        )
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
