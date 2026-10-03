"""The exception agent's five tools (TDD Part 2, "Tools"; batch 6, CHG-008,
S3-S4). Each has a Pydantic args model (extra keys refused) and its
permissions written down as annotations, which docs/notes/agent-permissions.md
is generated from. A name not in TOOLS is refused by the loop.

None of them changes the ledger: search_gmail, get_ledger and run_planner
read; add_candidate writes a candidate row (and, for a message the mail poll
never stored, that message as a NEW source document, encrypted like every
stored email, which the pipeline reads when the case ends); ask_owner writes
one owner question and ends the run. An agent's candidate is evidence for its
case only: the owner never sees it as an entry to confirm (app/web/repo.py),
and it counts in no duplicate check (app/db/read.py)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.cases import Case
from app.ai.extract import BankAlertExtract, InvoiceExtract, InvoiceLine
from app.clock import Clock
from app.db.read import accounts_of, bank_txn_with_key, business_name, invoice_on_record, what_if_snapshot
from app.domain.money import format_inr, parse_inr
from app.ingest.eml_folder import parse_message, sender_address, sent_at
from app.ingest.mail_source import MailSource, MessageRef
from app.ingest.store import DocumentStore
from app.planner.plan import plan
from app.validate import NO_DUE_DATE, failures
from app.validate.alert import MailFacts, check_bank_alert
from app.validate.invoice import check_invoice

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
    store: DocumentStore | None = None  # where add_candidate keeps a message the poll never stored


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


# --- add_candidate ----------------------------------------------------------------------

MAX_QUESTION = 300
MAX_CHOICES = 4


class CandidateArgs(_Args):
    record_type: Literal["bank_alert", "invoice"]
    message_id: str = Field(min_length=1, max_length=200)
    fields: dict[str, Any]


def _document_for(ctx: ToolContext, message_id: str, raw: bytes) -> int:
    """The source document of a message found by search: the one the poll
    stored, or the message stored now (encrypted), like the poll does."""
    msg = parse_message(raw)
    external_ref = str(msg.get("Message-ID") or "").strip() or f"sha256:{hashlib.sha256(raw).hexdigest()}"
    sha = hashlib.sha256(raw).hexdigest()
    row = ctx.conn.execute(
        "SELECT id FROM source_document WHERE business_id = ? AND (content_sha256 = ? OR "
        "(kind = 'email' AND external_ref = ?))", (ctx.case.business_id, sha, external_ref)).fetchone()
    if row is not None:
        return row[0]
    if ctx.store is None:
        raise ValueError("no document store is set up (FERNET_KEY) to keep the message")
    at = sent_at(msg)
    doc_id = ctx.conn.execute(
        "INSERT INTO source_document (business_id, kind, external_ref, content_sha256, received_at, storage_path, "
        "status) VALUES (?, 'email', ?, ?, ?, ?, 'NEW')",
        (ctx.case.business_id, external_ref, sha, (at or ctx.clock.now()).isoformat(), ctx.store.put(raw, sha)),
    ).lastrowid
    # NEW: the pipeline has not read it. When the case ends, code hands it to the
    # pipeline (app/jobs/run_case.py), unless the case's own answer applied it.
    ctx.case.state.setdefault("stored_documents", []).append(doc_id)
    ctx.case.state.setdefault("document_messages", {})[str(doc_id)] = message_id
    return doc_id


def schema_problems(e: ValidationError, model: type[BaseModel]) -> str:
    """Every field a proposed record is missing or has wrongly, by name, and
    the fields it should have, so the agent can fix its call (CHG-031)."""
    errors = e.errors()
    path = lambda x: ".".join(map(str, x["loc"]))  # noqa: E731 - lines.0.amount_text, not just lines
    missing = sorted({path(x) for x in errors if x["type"] == "missing" and x["loc"]})
    unknown = sorted({path(x) for x in errors if x["type"] == "extra_forbidden" and x["loc"]})
    parts = ([f"missing {', '.join(missing)}"] if missing else []) + (
        [f"not fields of this record: {', '.join(unknown)}"] if unknown else [])
    parts += [f"{path(x)}: {x['msg']}" for x in errors if x["type"] not in ("missing", "extra_forbidden")]
    out = "; ".join(parts) + f". Its fields are: {', '.join(model.model_fields)}"
    if model is InvoiceExtract and any(x["loc"][:1] == ("lines",) and len(x["loc"]) > 1 for x in errors):
        out += f"; each of lines has: {', '.join(InvoiceLine.model_fields)}"
    return out


def add_candidate(ctx: ToolContext, args: CandidateArgs) -> str:
    """A record read from a message this case's searches found, put through
    the pipeline's own rule checks (pure, app/validate). It never writes the
    ledger and never reaches the owner by itself: what a VALID candidate leads
    to is decided by code when the case ends (app/jobs/run_case.py). A
    candidate that fails counts toward the case's limit of 2."""
    if args.message_id not in ctx.case.seen_message_ids:
        return f"refused: message {args.message_id} did not come from this case's searches"
    model = BankAlertExtract if args.record_type == "bank_alert" else InvoiceExtract
    try:
        extract = model.model_validate(args.fields)
        schema_error = None
    except ValidationError as e:
        extract, schema_error = None, schema_problems(e, model)
    raw = ctx.mail.fetch(MessageRef(args.message_id)).raw
    msg = parse_message(raw)
    bid = ctx.case.business_id
    if args.record_type == "bank_alert":
        checks, record = check_bank_alert(extract, schema_error, MailFacts(sender_address(msg), sent_at(msg)),
                                          accounts_of(ctx.conn, bid), lambda k: bank_txn_with_key(ctx.conn, k))
        record_type, payload_record = "txn", None if record is None else json.loads(json.dumps(
            asdict(record), default=str))
        payload = {"doc_type": "bank_alert", "record": payload_record,
                   "dedup_key": record.dedup_key if record else None}
    else:
        checks, record, reading = check_invoice(extract, schema_error, business_name(ctx.conn, bid),
                                                lambda key: invoice_on_record(ctx.conn, bid, key))
        record_type = "payable" if reading.get("kind", "bill") == "bill" else "receivable"
        payload = {"doc_type": "invoice", "record": reading or None,
                   "party_gstin": record.key.party_gstin if record else None,
                   "payee": None if extract is None else {"account": extract.payee_account_number,
                                                          "ifsc": extract.payee_ifsc}}
    payload["extract"] = None if extract is None else extract.model_dump(mode="json")
    payload["found_by"] = f"agent:case:{ctx.case.id} via gmail:{args.message_id}"
    status = "VALID" if record is not None else "INVALID"
    # A bill with no due date: the agent can't supply one without making it up, and the pipeline that reads the
    # handed-on message flags the field for the owner. So it is evidence like any other (CHG-030 x CHG-031).
    no_due_date = (args.record_type == "invoice" and failures(checks) == {"dates": NO_DUE_DATE}
                   and not any(v.startswith("skipped") for v in checks.values()))  # every other check ran
    if no_due_date:
        status = "VALID"
    cid = ctx.conn.execute(
        "INSERT INTO candidate (source_document_id, record_type, payload_json, checks_json, status, attempts, "
        "created_by, created_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (_document_for(ctx, args.message_id, raw), record_type, json.dumps(payload, sort_keys=True),
         json.dumps(checks), status, f"agent:case:{ctx.case.id}", ctx.clock.now().isoformat()),
    ).lastrowid
    ctx.case.state.setdefault("candidates", {})[str(cid)] = {
        "status": status, "record_type": args.record_type, "message_id": args.message_id}
    if status == "INVALID":
        ctx.case.validation_failures += 1
        bad = "; ".join(f"{k}: {v}" for k, v in sorted(failures(checks).items())) or "a check was skipped"
        return f"candidate {cid}: INVALID ({bad})"
    if no_due_date:
        return f"candidate {cid}: VALID; it gives no due date, which the owner fills in (leave due_date null)"
    return f"candidate {cid}: VALID, every rule check passed"


# --- ask_owner --------------------------------------------------------------------------


class AskArgs(_Args):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    choices: list[str] = Field(min_length=1, max_length=MAX_CHOICES)  # the owner answers by choosing


def ask_owner(ctx: ToolContext, args: AskArgs) -> str:
    """One open question per case; shown as plain text; it ends the run. The
    owner is asked once: a case resumed by an answer ends with a final answer,
    which code takes to the owner if it must (app/jobs/run_case.py)."""
    if any(len(c) > 60 or not c.strip() for c in args.choices):
        return "refused: each choice is 1 to 60 characters"
    if ctx.case.state.get("resumed"):
        return "refused: the owner has answered this case once; give a final answer"
    return open_question(ctx, args.question, args.choices)


def open_question(ctx: ToolContext, question: str, choices: list[str]) -> str:
    """Opens the case's agent_question, unless one is open already."""
    open_q = ctx.conn.execute("SELECT id FROM owner_question WHERE case_id = ? AND status = 'OPEN' "
                              "AND kind = 'agent_question'", (ctx.case.id,)).fetchone()
    if open_q is not None:
        return f"refused: question {open_q[0]} for this case is still open"
    qid = ctx.conn.execute(
        "INSERT INTO owner_question (business_id, case_id, kind, body_text, choices_json, status) "
        "VALUES (?, ?, 'agent_question', ?, ?, 'OPEN')",
        (ctx.case.business_id, ctx.case.id, question.strip(),
         json.dumps({"case_id": ctx.case.id, "choices": [c.strip() for c in choices]})),
    ).lastrowid
    ctx.case.status = "ASK_OWNER"
    return f"question {qid} asked; this run ends until the owner answers"


TOOLS: dict[str, ToolSpec] = {
    "search_gmail": ToolSpec("search_gmail", SearchArgs, search_gmail, frozenset({"read_only", "reads_mail"}),
                             "Searches this business's mailbox; remembers the message IDs it returns."),
    "get_ledger": ToolSpec("get_ledger", LedgerArgs, get_ledger, frozenset({"read_only"}),
                           "Reads ledger rows on a read-only connection; at most 50."),
    "run_planner": ToolSpec("run_planner", PlannerArgs, run_planner, frozenset({"read_only"}),
                            "A what-if plan; writes nothing."),
    "add_candidate": ToolSpec("add_candidate", CandidateArgs, add_candidate, frozenset({"writes_candidate"}),
                              "Proposes a record from a message this case found; rule-checked; never the ledger."),
    "ask_owner": ToolSpec("ask_owner", AskArgs, ask_owner, frozenset({"asks_owner", "ends_run"}),
                          "One plain-text question (at most 300 characters, 4 choices); ends the run."),
}
