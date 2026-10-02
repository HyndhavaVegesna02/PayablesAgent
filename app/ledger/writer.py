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
    e.g. PF and ESI sharing one combined bill. A MISSING amount creates no payable
    yet, because a payable cannot exist without an amount."""
    who = parse_actor(actor)
    _check_role(who, CREATE_RULES["payable"]["DRAFT"], "create a tax obligation")
    _require_fk(conn)
    clock = clock or SystemClock()
    kw = dict(actor=actor, reason=reason, source_ref=source_ref, trace_run_id=trace_run_id, clock=clock)
    with atomic(conn):
        _check_owner(conn, who, new.business_id)
        if payable_id is not None:
            linked = _get(conn, "payable", payable_id)
            if linked["priority"] != "statutory" or linked["business_id"] != new.business_id:
                raise ValueError(f"payable {payable_id} is not a statutory payable of this business")
        elif new.amount_status != "MISSING":
            payable = _create(
                conn,
                "payable",
                {
                    "business_id": new.business_id,
                    "invoice_number": invoice_number or f"{new.tax_type}-{new.period}",
                    "amount_paise": payable_amount_paise or new.amount_paise,
                    "due_date": new.due_date,
                    "priority": "statutory",
                    "status": "DRAFT",
                },
                **kw,
            )
            payable_id = payable["id"]
        row = _create(conn, "tax_obligation", {**new.model_dump(), "payable_id": payable_id}, **kw)
    return TaxObligation.model_validate(row)
