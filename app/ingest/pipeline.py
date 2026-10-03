"""The poll_mail and process_document jobs (TDD Part 2, "Jobs and the document
pipeline" and "Gmail ingestion"; batch 2 plan, CHG-004).

poll_mail stores each new message, encrypted, as a source document and queues
one process_document per document. The unique keys on source_document make a
re-poll harmless: a message already stored is skipped.

process_document runs the pipeline for one document: an email (its text and
any PDF or photo attached), or an uploaded photo, PDF or voice note.
1. sort (Gemini, low thinking). Irrelevant mail stops here.
3. extract (Gemini, medium), for bank alerts, failure/return notices and
   invoices.
4. validate with every rule check; a failure triggers one more extraction
   with the failed checks attached. Two failures are never retried: a field
   the model marks as uncertain goes to the owner at once, and a pure
   duplicate of a stored transaction is set aside.
5. a second failure is extracted once more at high thinking; if that fails
   too, the owner is asked to confirm the record.
6. route: a bank alert is written to the ledger by the pipeline and
   reconcile_txn is queued; a failure notice queues reconcile_failure; an
   invoice waits for the owner to confirm it (confirm_record), and the same
   invoice from a second source is set aside as a duplicate.

The AI calls run before any database write; everything the job decides is
then written in one transaction, so a crash or an AI outage part-way leaves
nothing behind and the job queue simply retries."""

from __future__ import annotations

import functools
import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

from app.ai.client import AIResult, AIUnavailable, Backend, Contents, Part
from app.ai.email_text import email_text
from app.ai.extract import extract_document, prompt_version
from app.ai.sort import sort_document
from app.clock import TIMEZONE
from app.config import Settings
from app.db.read import (
    accounts_of,
    bank_txn_with_key,
    business_name,
    failure_candidate_with_key,
    invoice_on_record,
    statement_with_key,
    vendor_party,
)
from app.domain.models import BankTxnNew
from app.domain.money import format_inr
from app.ingest.eml_folder import EmlFolderSource, attachments, parse_message, sender_address, sent_at
from app.ingest.files import readable, sniff_mime
from app.ingest.pdf import is_locked, locked_attachments
from app.ingest.mail_source import MailSource
from app.ingest.store import DocumentStore, StoreKeyError
from app.jobs import queue
from app.jobs.queue import DEFAULT_BUSINESS_ID, PermanentJobError
from app.ledger import writer
from app.validate import failures
from app.validate.alert import (
    AlertRecord,
    FailureRecord,
    MailFacts,
    check_bank_alert,
    check_failure_notice,
)
from app.validate.bank import account_last4, normalise_ifsc
from app.validate.duplicates import normalise_reference, txn_dedup_key
from app.validate.gstin import normalise_gstin
from app.validate.invoice import InvoiceRecord, check_invoice
from app.validate.statement import StatementRecord, check_statement
from app.validate.voice import check_voice

if TYPE_CHECKING:
    from app.worker import Handler, JobContext

LATER = {"challan", "payment_confirmation"}
UPLOAD_WORDS = {"photo": "photo", "pdf": "PDF", "voice": "voice note"}


def _ai_failure(e: AIUnavailable) -> Exception:
    return e if e.retryable else PermanentJobError(str(e))


# --- poll_mail ----------------------------------------------------------------------


def mail_source(settings: Settings, clock) -> MailSource:
    if settings.mail_source == "eml_folder":
        return EmlFolderSource(settings.test_inbox_path, clock)
    raise PermanentJobError("MAIL_SOURCE=gmail is not available yet (Gmail lands with CHG-009)")


def document_store(settings: Settings) -> DocumentStore:
    try:
        return DocumentStore(settings.data_dir, settings.fernet_key)
    except StoreKeyError as e:
        raise PermanentJobError(str(e)) from None


def _since(conn: sqlite3.Connection, source: str, business_id: int) -> date:
    """One day before the last sync, so nothing at the boundary is missed;
    before the first sync, the date the ledger's opening balance was taken."""
    row = conn.execute("SELECT last_synced_at FROM sync_state WHERE source = ?", (source,)).fetchone()
    if row is not None and row[0]:
        return datetime.fromisoformat(row[0]).astimezone(TIMEZONE).date() - timedelta(days=1)
    row = conn.execute(
        "SELECT MIN(opening_balance_at) FROM bank_account WHERE business_id = ?", (business_id,)
    ).fetchone()
    return date.fromisoformat(row[0]) if row[0] else date.min


def handle_poll_mail(ctx: JobContext, *, source: MailSource | None = None) -> None:
    business_id = ctx.payload.get("business_id", DEFAULT_BUSINESS_ID)
    source = source or mail_source(ctx.settings, ctx.clock)
    store = document_store(ctx.settings)
    conn = ctx.conn
    senders = sorted({s for a in accounts_of(conn, business_id) for s in a.alert_senders}
                     | {s.lower() for s in ctx.app_config.mail.vendor_senders})
    since = _since(conn, ctx.settings.mail_source, business_id)
    stored = skipped = 0
    for ref in source.list_new(since, senders):
        raw = source.fetch(ref).raw
        sha = hashlib.sha256(raw).hexdigest()
        msg = parse_message(raw)
        external_ref = str(msg.get("Message-ID") or "").strip() or f"sha256:{sha}"
        seen = conn.execute(
            "SELECT id, status FROM source_document WHERE business_id = ? "
            "AND (content_sha256 = ? OR (kind = 'email' AND external_ref = ?))",
            (business_id, sha, external_ref),
        ).fetchone()
        if seen is not None:
            skipped += 1
            if seen["status"] == "NEW":  # stored (by the exception agent) but never read: read it now
                queue.enqueue(conn, kind="process_document", payload={"document_id": seen["id"]},
                              idempotency_key=f"process_document:{seen['id']}", clock=ctx.clock)
            continue
        at = sent_at(msg)
        cur = conn.execute(
            "INSERT INTO source_document (business_id, kind, external_ref, content_sha256, received_at, "
            "storage_path, status) VALUES (?, 'email', ?, ?, ?, ?, ?)",
            (business_id, external_ref, sha, (at or ctx.clock.now()).isoformat(), store.put(raw, sha),
             "NEW" if at is not None else "FAILED"),
        )
        doc_id = cur.lastrowid
        stored += 1
        if at is None:
            ctx.tracer.step(input_ref=f"source_document:{doc_id}", tool="poll_mail",
                            result="no readable Date header: stored as FAILED, not processed")
            continue
        queue.enqueue(conn, kind="process_document", payload={"document_id": doc_id},
                      idempotency_key=f"process_document:{doc_id}", clock=ctx.clock)
    conn.execute(
        "INSERT INTO sync_state (source, last_synced_at) VALUES (?, ?) "
        "ON CONFLICT(source) DO UPDATE SET last_synced_at = excluded.last_synced_at",
        (ctx.settings.mail_source, ctx.clock.now().isoformat()),
    )
    ctx.tracer.step(tool="poll_mail", arguments={"since": since.isoformat(), "senders": senders},
                    result=f"{stored} stored, {skipped} already seen")


# --- process_document ---------------------------------------------------------------


@dataclass
class Attempt:
    thinking: str
    result: AIResult
    checks: dict[str, str]


@dataclass
class Outcome:
    status: str  # candidate status: VALID, INVALID (duplicate) or AWAITING_OWNER
    attempts: list[Attempt]
    record: AlertRecord | FailureRecord | InvoiceRecord | StatementRecord | None
    reading: dict[str, Any] | None = None  # an invoice's best reading so far, for the owner's form


# check(extract, schema_error) -> (checks, record when every check passed, best reading)
Checker = Callable[[Any, str | None], tuple[dict[str, str], Any, dict[str, Any] | None]]


def checker(conn: sqlite3.Connection, doc_type: str, mail: MailFacts, business_id: int) -> Checker:
    if doc_type == "bank_alert":
        accounts = accounts_of(conn, business_id)
        return lambda x, err: (*check_bank_alert(x, err, mail, accounts, lambda k: bank_txn_with_key(conn, k)), None)
    if doc_type == "failure_notice":
        accounts = accounts_of(conn, business_id)
        return lambda x, err: (*check_failure_notice(
            x, err, mail, accounts, lambda k: failure_candidate_with_key(conn, k)), None)
    if doc_type == "statement":
        accounts = accounts_of(conn, business_id)
        return lambda x, err: check_statement(x, err, mail, accounts, lambda k: statement_with_key(conn, k))
    if doc_type == "voice_note":
        return lambda x, err: check_voice(x, err, lambda key: invoice_on_record(conn, business_id, key))
    if doc_type == "invoice":
        name = business_name(conn, business_id)
        return lambda x, err: check_invoice(x, err, name, lambda key: invoice_on_record(conn, business_id, key))
    raise ValueError(f"no checks for {doc_type}")


def extract_with_retries(ctx: JobContext, backend: Backend, doc_type: str, contents: Contents, check: Checker,
                         input_ref: str) -> Outcome:
    """Steps 3-5: extract, check, re-extract with the failures attached, then
    once more at high thinking. Two failures stop the ladder at once:
    - a field the model marks as uncertain goes to the owner (TDD Part 1:
      "fields the model marks as uncertain are flagged for the owner"); asking
      the model again would only invite it to drop the flag;
    - a reply that only repeats a record already in the ledger is not
      retried: reading it again cannot change that."""
    first = ctx.app_config.model.thinking.extract
    ladder = [first] * ctx.app_config.escalation.max_validation_failures + ["high"]
    attempts: list[Attempt] = []
    previous, failed_checks = None, None
    reading = None
    for thinking in ladder:
        try:
            r = extract_document(doc_type, contents, thinking=thinking, backend=backend,
                                 app_config=ctx.app_config, tracer=ctx.tracer, input_ref=input_ref,
                                 previous=previous, failed_checks=failed_checks)
        except AIUnavailable as e:
            raise _ai_failure(e) from e
        checks, record, reading = check(r.parsed, r.schema_error)
        attempts.append(Attempt(thinking, r, checks))
        fails = failures(checks)
        ctx.tracer.step(input_ref=input_ref, tool="validate", validation=checks,
                        retries=len(attempts) - 1,
                        result="all checks passed" if record else f"failed: {sorted(fails)}")
        if record is not None:
            return Outcome("VALID", attempts, record, reading)
        if "confidence" in fails or (doc_type == "voice_note" and "amount" in fails):
            # an amount the code can't read stays unreadable however often it is asked (Q8)
            return Outcome("AWAITING_OWNER", attempts, None, reading)
        if set(fails) == {"duplicates"}:
            return Outcome("INVALID", attempts, None, reading)
        previous, failed_checks = r.text, fails
    return Outcome("AWAITING_OWNER", attempts, None, reading)


def document_contents(doc: sqlite3.Row, raw: bytes) -> tuple[Contents, MailFacts, EmailMessage | None]:
    """What the model is shown: an email's headers and text, then any PDF or
    photo attached; an upload as the file itself, after one line saying what
    it is."""
    if doc["kind"] == "email":
        msg = parse_message(raw)
        text = email_text(msg)
        files = [Part(a.content_type, a.data) for a in attachments(msg) if a.data and readable(a.content_type)]
        return (text if not files else [text, *files]), MailFacts(sender_address(msg), sent_at(msg)), msg
    mime = sniff_mime(raw, doc["kind"])
    if mime is None:
        raise PermanentJobError(f"source_document {doc['id']} is not a photo, PDF or voice note the model can read")
    return [f"A {UPLOAD_WORDS[doc['kind']]} uploaded to the app.", Part(mime, raw)], MailFacts(None, None), None


def handle_process_document(ctx: JobContext, *, backend: Backend) -> None:
    conn = ctx.conn
    doc = conn.execute("SELECT * FROM source_document WHERE id = ?",
                       (ctx.payload.get("document_id"),)).fetchone()
    if doc is None:
        raise PermanentJobError(f"source_document {ctx.payload.get('document_id')} does not exist")
    if doc["status"] != "NEW":
        ctx.tracer.step(input_ref=f"source_document:{doc['id']}", tool="process_document",
                        result=f"already {doc['status']}; nothing to do")
        return
    input_ref = f"source_document:{doc['id']}"
    try:
        raw = document_store(ctx.settings).get(doc["storage_path"])
    except StoreKeyError as e:
        raise PermanentJobError(str(e)) from None
    if _locked(doc, raw):
        with writer.atomic(conn):
            conn.execute("UPDATE source_document SET status = 'LOCKED' WHERE id = ?", (doc["id"],))
            conn.execute(
                "INSERT INTO owner_question (business_id, kind, body_text, choices_json, status) "
                "VALUES (?, 'unlock_pdf', ?, ?, 'OPEN')",
                (doc["business_id"], "A PDF needs its password before it can be read. Type it below: it is used "
                 "once to open the file and is never stored.", json.dumps({"document_id": doc["id"]})),
            )
        ctx.tracer.step(input_ref=input_ref, tool="unlock",
                        result="password-protected PDF: LOCKED; the owner is asked for the password (unlock_pdf)")
        return
    contents, mail, msg = document_contents(doc, raw)

    if doc["kind"] == "voice":
        doc_type = "voice_note"  # read in one call, transcript and bill together (TDD "AI model"): no sort
    else:
        try:
            sorted_ = sort_document(contents, backend=backend, app_config=ctx.app_config, tracer=ctx.tracer,
                                    input_ref=input_ref)
        except AIUnavailable as e:
            raise _ai_failure(e) from e
        if sorted_.parsed is None:
            raise RuntimeError(f"the sort reply did not match the schema: {sorted_.schema_error}")
        doc_type = sorted_.parsed.doc_type

    if doc_type == "irrelevant" or doc_type in LATER:
        status = "IRRELEVANT" if doc_type == "irrelevant" else "PROCESSED"
        with writer.atomic(conn):
            conn.execute("UPDATE source_document SET doc_type = ?, status = ? WHERE id = ?",
                         (doc_type, status, doc["id"]))
        ctx.tracer.step(input_ref=input_ref, tool="route",
                        result="irrelevant: stopped after sort" if status == "IRRELEVANT"
                        else f"{doc_type}: not extracted yet (CHG-007, a later slice)")
        return

    check = checker(conn, doc_type, mail, doc["business_id"])
    outcome = extract_with_retries(ctx, backend, doc_type, contents, check, input_ref)
    with writer.atomic(conn):
        candidate_id = _store_candidate(ctx, doc, doc_type, outcome)
        _route(ctx, doc, doc_type, outcome, candidate_id, msg)
        conn.execute("UPDATE source_document SET doc_type = ?, status = 'PROCESSED' WHERE id = ?",
                     (doc_type, doc["id"]))


def _locked(doc: sqlite3.Row, raw: bytes) -> bool:
    """Pipeline step 2: a password-protected PDF, uploaded or attached."""
    if doc["kind"] == "pdf":
        return is_locked(raw)
    if doc["kind"] == "email":
        return bool(locked_attachments(parse_message(raw)))
    return False


def _store_candidate(ctx: JobContext, doc: sqlite3.Row, doc_type: str, outcome: Outcome) -> int:
    last = outcome.attempts[-1]
    extract = None if last.result.parsed is None else last.result.parsed.model_dump(mode="json")
    transcript = None
    if doc_type in ("invoice", "voice_note"):
        reading = outcome.reading or {}
        transcript = (extract or {}).get("transcript")
        record_type = "payable" if reading.get("kind", "bill") == "bill" else "receivable"
        payload = {
            "doc_type": doc_type, "extract": extract, "record": reading or None,
            "party_gstin": outcome.record.key.party_gstin if outcome.record else None,
            "payee": None if extract is None else {"account": extract.get("payee_account_number"),
                                                   "ifsc": extract.get("payee_ifsc")},
        }
    else:
        record_type = "statement" if doc_type == "statement" else "txn"
        record = None if outcome.record is None else json.loads(json.dumps(asdict(outcome.record), default=str))
        payload = {"doc_type": doc_type, "extract": extract, "record": record,
                   "dedup_key": record["dedup_key"] if record else None}
    cur = ctx.conn.execute(
        "INSERT INTO candidate (source_document_id, record_type, payload_json, transcript, model_id, thinking, "
        "prompt_version, checks_json, status, attempts, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pipeline', ?)",
        (doc["id"], record_type, json.dumps(payload, sort_keys=True), transcript, ctx.app_config.model.id,
         last.thinking,
         prompt_version(ctx.app_config, doc_type), json.dumps(last.checks), outcome.status,
         len(outcome.attempts), ctx.clock.now().isoformat()),
    )
    return cur.lastrowid


def _source_words(doc: sqlite3.Row, msg: EmailMessage | None) -> str:
    if msg is not None:
        return f"the email \"{msg.get('Subject', '')}\""
    return f"an uploaded {UPLOAD_WORDS.get(doc['kind'], 'file')}"


def _ask_owner(ctx: JobContext, doc: sqlite3.Row, candidate_id: int, body: str) -> None:
    ctx.conn.execute(
        "INSERT INTO owner_question (business_id, kind, body_text, choices_json, status) "
        "VALUES (?, 'confirm_record', ?, ?, 'OPEN')",
        (doc["business_id"], body, json.dumps({"candidate_id": candidate_id})),
    )


def _check_bank_details(ctx: JobContext, doc: sqlite3.Row, outcome: Outcome, candidate_id: int) -> None:
    """Bank details on a vendor's bill that differ from the ones on record, or
    are the vendor's first (D26), mark the vendor change_pending and ask the
    owner (approve_bank_change); they are never stored automatically (TDD
    pipeline step 6; batch 5, S4). Run
    on every reading, a duplicate included: "same invoice, new account" is
    the classic fraud."""
    x = outcome.attempts[-1].result.parsed
    reading = outcome.reading or {}
    if x is None or reading.get("kind") != "bill" or not hasattr(x, "payee_account_number"):
        return  # a voice note carries no bank details
    last4, ifsc = account_last4(x.payee_account_number), normalise_ifsc(x.payee_ifsc)
    if last4 is None and ifsc is None:
        return
    party = vendor_party(ctx.conn, doc["business_id"], reading.get("party"), normalise_gstin(x.seller_gstin))
    if party is None:
        return  # a new vendor: compared when the owner confirms the bill for a vendor on record
    input_ref = f"source_document:{doc['id']}"
    if writer.flag_bank_change(party["id"], candidate_id, last4, ifsc, "pipeline",
                               f"candidate {candidate_id} gives different bank details", input_ref,
                               conn=ctx.conn, clock=ctx.clock, trace_run_id=ctx.tracer.run_id):
        ctx.tracer.step(input_ref=input_ref, tool="route", escalation_rule="bank_change",
                        result=f"party {party['id']} bank change pending; approve_bank_change asked")


def _route_invoice(ctx: JobContext, doc: sqlite3.Row, outcome: Outcome, candidate_id: int,
                   msg: EmailMessage | None) -> None:
    input_ref = f"source_document:{doc['id']}"
    fails = failures(outcome.attempts[-1].checks)
    _check_bank_details(ctx, doc, outcome, candidate_id)
    if outcome.status == "INVALID":
        ctx.tracer.step(input_ref=input_ref, tool="route", result=f"duplicate: {fails['duplicates']}")
        return
    reading = outcome.reading or {}
    what = "bill" if reading.get("kind", "bill") == "bill" else "sales invoice"
    amount = reading.get("amount_paise")
    body = (f"Please check this {what} from {_source_words(doc, msg)}: {reading.get('party') or 'unknown party'}"
            + (f", {format_inr(amount)}" if type(amount) is int else "") + ".")
    if fails:
        body += (f" It was read {len(outcome.attempts)} times and these checks still fail: "
                 + "; ".join(f"{k} ({v})" for k, v in sorted(fails.items())) + ".")
    _ask_owner(ctx, doc, candidate_id, body)
    ctx.tracer.step(input_ref=input_ref, tool="route",
                    escalation_rule="max_validation_failures" if fails else None,
                    result=f"{what}, candidate {candidate_id}: the owner confirms it (confirm_record)")


def _route_statement(ctx: JobContext, doc: sqlite3.Row, outcome: Outcome, candidate_id: int,
                     msg: EmailMessage | None) -> None:
    """Pipeline step 6 for a statement: rows the ledger is missing are added
    (and reconciled), rows already there are confirmed, and the closing
    balance goes to the drift check. Rows before the account's opening
    balance date are already in that balance and are left alone."""
    conn, input_ref = ctx.conn, f"source_document:{doc['id']}"
    fails = failures(outcome.attempts[-1].checks)
    if outcome.status == "INVALID":
        ctx.tracer.step(input_ref=input_ref, tool="route", result=f"duplicate: {fails['duplicates']}")
        return
    if outcome.status == "AWAITING_OWNER":
        _ask_owner(ctx, doc, candidate_id,
                   f"A bank statement from {_source_words(doc, msg)} could not be read reliably: "
                   + "; ".join(f"{k} ({v})" for k, v in sorted(fails.items()))
                   + ". Nothing from it was written; the drift check against the next alert or statement "
                   "still guards the balance. Reject it, or ask the bank for a clearer copy.")
        ctx.tracer.step(input_ref=input_ref, tool="route", escalation_rule="max_validation_failures",
                        result=f"statement candidate {candidate_id} awaits the owner")
        return
    rec = outcome.record
    opened = conn.execute("SELECT opening_balance_at FROM bank_account WHERE id = ?", (rec.account_id,)).fetchone()[0]
    since = date.fromisoformat(opened[:10])
    existing: dict[tuple, list[str | None]] = {}
    for d, direction, amount, ref in conn.execute(
        "SELECT txn_date, direction, amount_paise, reference FROM bank_txn WHERE account_id = ? "
        "AND status <> 'ADJUSTMENT'", (rec.account_id,)
    ).fetchall():
        existing.setdefault((d, direction, amount), []).append(normalise_reference(ref))
    added, confirmed = [], 0
    for row in rec.rows:
        if row.txn_date < since:
            continue
        same = existing.get((row.txn_date.isoformat(), row.direction, row.amount_paise), [])
        if same:  # already in the ledger: one statement row confirms one transaction
            same.remove(row.reference if row.reference in same else same[0])
            confirmed += 1
            continue
        # Missing from the ledger: every row the existing transactions did not
        # account for is added, so two identical charges on one day are two.
        base = key = txn_dedup_key(rec.account_id, row.txn_date, row.direction, row.amount_paise, row.reference)
        n = 1
        while bank_txn_with_key(conn, key) is not None:
            n += 1
            key = f"{base}#{n}"
        txn = writer.create_bank_txn(
            BankTxnNew(account_id=rec.account_id, direction=row.direction, amount_paise=row.amount_paise,
                       txn_date=row.txn_date, counterparty=row.counterparty, reference=row.reference,
                       dedup_key=key, source_document_id=doc["id"], candidate_id=candidate_id, status="UNMATCHED"),
            actor="pipeline", reason=f"statement row missing from the ledger, candidate {candidate_id}",
            source_ref=input_ref, conn=conn, clock=ctx.clock, trace_run_id=ctx.tracer.run_id,
        )
        queue.enqueue(conn, kind="reconcile_txn", payload={"bank_txn_id": txn.id},
                      idempotency_key=f"reconcile_txn:{txn.id}", clock=ctx.clock)
        added.append(txn.id)
    reported_at = datetime.combine(rec.period_to, time(23, 59), tzinfo=TIMEZONE)
    drift = queue.enqueue(
        conn, kind="drift_check",
        payload={"account_id": rec.account_id, "source": "statement", "reported_paise": rec.closing_paise,
                 "reported_at": reported_at.isoformat()},
        idempotency_key=f"drift_check:statement:{candidate_id}", clock=ctx.clock,
    )
    ctx.tracer.step(input_ref=input_ref, tool="route",
                    result=f"statement: {len(added)} missing rows added {added}, {confirmed} already recorded; "
                           f"drift_check job {drift} queued")


def _route(ctx: JobContext, doc: sqlite3.Row, doc_type: str, outcome: Outcome, candidate_id: int,
           msg: EmailMessage | None) -> None:
    conn, input_ref = ctx.conn, f"source_document:{doc['id']}"
    if doc_type in ("invoice", "voice_note"):
        _route_invoice(ctx, doc, outcome, candidate_id, msg)
        return
    if doc_type == "statement":
        _route_statement(ctx, doc, outcome, candidate_id, msg)
        return
    if outcome.status == "AWAITING_OWNER":
        fails = failures(outcome.attempts[-1].checks)
        _ask_owner(ctx, doc, candidate_id,
                   f"Please check this bank email: \"{msg.get('Subject', '') if msg is not None else ''}\". "
                   f"It was read {len(outcome.attempts)} times and these checks still fail: "
                   + "; ".join(f"{k} ({v})" for k, v in sorted(fails.items())) + ".")
        ctx.tracer.step(input_ref=input_ref, tool="route", escalation_rule="max_validation_failures",
                        result=f"candidate {candidate_id} awaits the owner (confirm_record)")
        return
    if outcome.status == "INVALID":
        ctx.tracer.step(input_ref=input_ref, tool="route",
                        result=f"duplicate: {failures(outcome.attempts[-1].checks)['duplicates']}")
        return
    rec = outcome.record
    if doc_type == "bank_alert":
        txn = writer.create_bank_txn(
            BankTxnNew(account_id=rec.account_id, direction=rec.direction, amount_paise=rec.amount_paise,
                       txn_date=rec.txn_date, counterparty=rec.counterparty, reference=rec.reference,
                       balance_after_paise=rec.balance_after_paise, dedup_key=rec.dedup_key,
                       source_document_id=doc["id"], candidate_id=candidate_id, status="UNMATCHED"),
            actor="pipeline", reason=f"bank alert, candidate {candidate_id}", source_ref=input_ref,
            conn=conn, clock=ctx.clock, trace_run_id=ctx.tracer.run_id,
        )
        job_id = queue.enqueue(conn, kind="reconcile_txn", payload={"bank_txn_id": txn.id},
                               idempotency_key=f"reconcile_txn:{txn.id}", clock=ctx.clock)
        queued = f"reconcile_txn job {job_id}"
        if rec.balance_after_paise is not None:
            # Queued after reconcile_txn, so the match is in the ledger before the comparison.
            drift = queue.enqueue(
                conn, kind="drift_check",
                payload={"account_id": rec.account_id, "source": "alert",
                         "reported_paise": rec.balance_after_paise, "reported_at": doc["received_at"]},
                idempotency_key=f"drift_check:bank_txn:{txn.id}", clock=ctx.clock,
            )
            queued += f" and drift_check job {drift}"
        ctx.tracer.step(input_ref=input_ref, tool="route", result=f"bank_txn {txn.id} written; {queued} queued")
    else:
        job_id = queue.enqueue(conn, kind="reconcile_failure", payload={"candidate_id": candidate_id},
                               idempotency_key=f"reconcile_failure:{candidate_id}", clock=ctx.clock)
        ctx.tracer.step(input_ref=input_ref, tool="route",
                        result=f"failure notice, candidate {candidate_id}; reconcile_failure job {job_id} queued")


def handlers(backend: Backend) -> dict[str, Handler]:
    return {
        "poll_mail": handle_poll_mail,
        "process_document": functools.partial(handle_process_document, backend=backend),
    }

