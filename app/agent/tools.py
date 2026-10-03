"""The exception agent's five tools (TDD Part 2, "Tools"; batch 6, CHG-008,
S3-S4). Each has a Pydantic args model (extra keys refused) and its
permissions written down as annotations, which docs/notes/agent-permissions.md
is generated from. A name not in TOOLS is refused by the loop.

None of them changes the ledger: search_gmail, get_ledger and run_planner
read; add_candidate writes a candidate row and nothing else; ask_owner writes
one owner question and ends the run."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.cases import Case
from app.clock import Clock
from app.db.read import what_if_snapshot
from app.domain.money import format_inr, parse_inr
from app.ingest.mail_source import MailSource
from app.planner.plan import plan

MAX_SEARCH = 20
MAX_ROWS = 50


@dataclass
class ToolContext:
    conn: sqlite3.Connection  # the job's connection: for the agent's own candidate and question rows only
    db_path: str  # get_ledger opens its own read-only connection on this file
    case: Case
    mail: MailSource
    clock: Clock
    step: int


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    args_model: type[_Args]
    run: Callable[[ToolContext, Any], str]
    annotations: frozenset[str]  # read_only, reads_mail, writes_candidate, asks_owner, ends_run
    summary: str


# --- search_gmail ---------------------------------------------------------------------


class SearchArgs(_Args):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=MAX_SEARCH)


def search_gmail(ctx: ToolContext, args: SearchArgs) -> str:
    """This business's mailbox only (the configured MailSource). Every message
    ID it returns is remembered: add_candidate and a final answer may cite
    only those."""
    found = ctx.mail.search(args.query, args.limit)
    seen = ctx.case.state.setdefault("seen_message_ids", [])
    lines = []
    for m in found:
        if m.ref.id not in seen:
            seen.append(m.ref.id)
        when = m.sent_at.isoformat() if m.sent_at else "no date"
        lines.append(f"message {m.ref.id} | {when} | from {m.sender} | {m.subject} | {m.snippet}")
    return "\n".join(lines) or "no messages match"


# --- get_ledger -------------------------------------------------------------------------


class LedgerArgs(_Args):
    table: Literal["bank_txn", "payable", "receivable", "party", "bank_account"]
    account: str | None = Field(default=None, pattern=r"^[0-9]{4}$")  # last four digits
    date_from: date | None = None
    date_to: date | None = None
    amount_text: str | None = None  # as written; code reads it
    party: str | None = Field(default=None, max_length=100)


_LEDGER_SQL = {
    "bank_txn": ("SELECT t.id, t.txn_date, t.direction, t.amount_paise, t.counterparty, t.reference, t.status, "
                 "a.account_mask FROM bank_txn t JOIN bank_account a ON a.id = t.account_id WHERE a.business_id = ?",
                 {"date": "t.txn_date", "amount": "t.amount_paise", "party": "t.counterparty",
                  "account": "a.account_mask"}, "t.txn_date DESC, t.id DESC"),
    "payable": ("SELECT p.id, pt.name AS party, p.invoice_number, p.amount_paise, p.due_date, p.planned_date, "
                "p.priority, p.status FROM payable p LEFT JOIN party pt ON pt.id = p.party_id WHERE p.business_id = ?",
                {"date": "p.due_date", "amount": "p.amount_paise", "party": "pt.name"}, "p.due_date, p.id"),
    "receivable": ("SELECT r.id, pt.name AS party, r.invoice_number, r.amount_paise, r.expected_date, r.confidence "
                   "FROM receivable r LEFT JOIN party pt ON pt.id = r.party_id WHERE r.business_id = ?",
                   {"date": "r.expected_date", "amount": "r.amount_paise", "party": "pt.name"}, "r.expected_date, r.id"),
    "party": ("SELECT id, kind, name, aliases_json, bank_status FROM party WHERE business_id = ?",
              {"party": "name"}, "id"),
    "bank_account": ("SELECT id, bank_name, account_mask, reported_balance_paise, drift_status FROM bank_account "
                     "WHERE business_id = ?", {"account": "account_mask"}, "id"),
}


def read_only(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _show(row: sqlite3.Row) -> str:
    return ", ".join(f"{k} {format_inr(row[k]) if k.endswith('_paise') and row[k] is not None else row[k]}"
                     for k in row.keys())


def get_ledger(ctx: ToolContext, args: LedgerArgs) -> str:
    """Read-only (its own mode=ro connection), this business's rows only, at
    most 50. The SQL is built by code from fixed pieces; values are bound."""
    sql, cols, order = _LEDGER_SQL[args.table]
    where, values = [sql], [ctx.case.business_id]
    if args.account is not None and "account" in cols:
        where.append(f"AND {cols['account']} LIKE ?")
        values.append(f"%{args.account}")
    if args.date_from is not None and "date" in cols:
        where.append(f"AND {cols['date']} >= ?")
        values.append(args.date_from.isoformat())
    if args.date_to is not None and "date" in cols:
        where.append(f"AND {cols['date']} <= ?")
        values.append(args.date_to.isoformat())
    if args.amount_text is not None and "amount" in cols:
        try:
            values.append(parse_inr(args.amount_text))
        except ValueError:
            return f"refused: {args.amount_text!r} is not an amount in rupees"
        where.append(f"AND {cols['amount']} = ?")
    if args.party is not None and "party" in cols:
        where.append(f"AND {cols['party']} LIKE ?")
        values.append(f"%{args.party}%")
    ro = read_only(ctx.db_path)
    try:
        rows = ro.execute(" ".join(where) + f" ORDER BY {order} LIMIT {MAX_ROWS + 1}", values).fetchall()
    finally:
        ro.close()
    lines = [_show(r) for r in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        lines.append(f"(truncated at {MAX_ROWS} rows)")
    return "\n".join(lines) or "no rows match"


# --- run_planner ------------------------------------------------------------------------


class PlannerArgs(_Args):
    drop_payable_ids: list[int] = Field(default_factory=list, max_length=20)
    receivable_dates: dict[int, date] = Field(default_factory=dict)


def run_planner(ctx: ToolContext, args: PlannerArgs) -> str:
    """A what-if plan on the current snapshot; it writes nothing."""
    try:
        s = what_if_snapshot(ctx.conn, ctx.case.business_id, ctx.clock.today(),
                             drop_payables=args.drop_payable_ids, receivable_dates=args.receivable_dates)
    except ValueError as e:
        return f"refused: {e}"
    r = plan(s)
    lines = [f"lowest balance {format_inr(r.lowest_balance_paise)} on {r.lowest_on.isoformat()}",
             f"first day below the safety amount: {r.breach_on.isoformat() if r.breach_on else 'none'}"]
    lines += [f"bill {ln.payable_id}: {ln.decision}{' on ' + ln.pay_on.isoformat() if ln.pay_on else ''}"
              for ln in r.lines]
    return "\n".join(lines)


TOOLS: dict[str, ToolSpec] = {
    "search_gmail": ToolSpec("search_gmail", SearchArgs, search_gmail, frozenset({"read_only", "reads_mail"}),
                             "Searches this business's mailbox; remembers the message IDs it returns."),
    "get_ledger": ToolSpec("get_ledger", LedgerArgs, get_ledger, frozenset({"read_only"}),
                           "Reads ledger rows on a read-only connection; at most 50."),
    "run_planner": ToolSpec("run_planner", PlannerArgs, run_planner, frozenset({"read_only"}),
                            "A what-if plan; writes nothing."),
}
