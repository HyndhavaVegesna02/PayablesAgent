"""Password-protected statements (batch 5 plan, S5; CHG-007 AC1; PO
requirement: the password never reaches the trace, the database, the logs
or job.last_error). A locked PDF waits for the owner's password, is opened
once in memory, and its statement then fills the ledger's missing rows and
reaches the drift check."""

import json
import logging
from email.message import EmailMessage
from pathlib import Path

import pymupdf
import pytest

from app.ai.client import Part
from app.domain.models import BankTxnNew
from app.ingest.pdf import is_locked
from app.ingest.store import DocumentStore
from app.jobs import queue
from app.ledger import writer
from app.validate import PASSED
from app.validate.alert import AccountIn, MailFacts
from app.validate.statement import check_statement
from app.web import actions
from app.web.auth import User
from app.worker import default_handlers
from tests.fake_ai import FakeBackend
from tests.web_helpers import login, make_web_env, post
from tests.worker_helpers import run_all

PASSWORD = "Zq7-statement-pw-4821"
HELPER = User(2, 1, "helper@example.test", "helper")
STATEMENT = {
    "account_last4": "4821", "period_from": "2026-10-12", "period_to": "2026-10-16",
    "opening_balance_text": "Rs.6,20,000.00", "closing_balance_text": "Rs.6,99,410.00",
    "rows": [
        {"txn_date": "2026-10-12", "direction": "debit", "amount_text": "1,80,000.00",
         "counterparty": "ASHIRWAD PAPER SUPPLIERS", "reference": "N286261234567"},
        {"txn_date": "2026-10-13", "direction": "debit", "amount_text": "590.00",
         "counterparty": "BANK CHARGES", "reference": None},
        {"txn_date": "2026-10-15", "direction": "credit", "amount_text": "2,60,000.00",
         "counterparty": "KAVERI TRADERS", "reference": "N289998765432"},
    ],
    "uncertain_fields": [],
}


def locked_pdf(text="HDFC Bank statement, account XXXX4821, 12-16 Oct 2026"):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=PASSWORD, owner_pw=PASSWORD)


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    env.clock.advance(env.clock.now().replace(day=16, hour=18) - env.clock.now())  # Fri 16 Oct, 18:00
    yield env, client
    env.conn.close()


def upload_locked(env):
    store = DocumentStore(env.settings.data_dir, env.settings.fernet_key)
    doc_id = actions.upload(env.conn, HELPER, locked_pdf(), "pdf", store, clock=env.clock)
    backend = FakeBackend()
    run_all(env, default_handlers(backend))
    return doc_id, backend


def reads_statement(reply=STATEMENT):
    return FakeBackend().queue("SortResult", {"doc_type": "statement", "reason": "a statement"}).queue(
        "StatementExtract", reply)


def doc_status(env, doc_id):
    return env.conn.execute("SELECT status FROM source_document WHERE id = ?", (doc_id,)).fetchone()[0]


def test_a_locked_pdf_waits_for_the_password_and_is_never_sent_to_the_model(web):
    env, client = web
    doc_id, backend = upload_locked(env)
    assert doc_status(env, doc_id) == "LOCKED" and backend.requests == []
    q = env.conn.execute("SELECT kind, choices_json FROM owner_question WHERE status = 'OPEN'").fetchone()
    assert q[0] == "unlock_pdf" and json.loads(q[1]) == {"document_id": doc_id}
    login(client)
    page = client.get("/attention").text
    assert f'action="/documents/{doc_id}/unlock"' in page and 'type="password"' in page


def test_the_password_unlocks_once_and_the_statement_fills_the_ledger(web):
    env, client = web
    writer.create_bank_txn(  # the Mon 12 debit, already in from its alert
        BankTxnNew(account_id=1, direction="debit", amount_paise=18_000_000, txn_date="2026-10-12",
                   counterparty="ASHIRWAD PAPER SUPPLIERS", reference="N286261234567",
                   dedup_key="1:2026-10-12:debit:18000000:N286261234567", status="UNMATCHED"),
        actor="pipeline", reason="alert", source_ref=None, conn=env.conn, clock=env.clock)
    env.conn.commit()
    doc_id, _ = upload_locked(env)
    csrf = login(client)
    assert post(client, f"/documents/{doc_id}/unlock", csrf, {"password": PASSWORD}).status_code == 303
    assert doc_status(env, doc_id) == "NEW"
    store = DocumentStore(env.settings.data_dir, env.settings.fernet_key)
    path = env.conn.execute("SELECT storage_path FROM source_document WHERE id = ?", (doc_id,)).fetchone()[0]
    assert not is_locked(store.get(path))  # the unlocked copy replaced the locked one
    backend = reads_statement()
    run_all(env, default_handlers(backend))
    sent = backend.calls("StatementExtract")[0].contents[-1]
    assert isinstance(sent, Part) and sent.mime_type == "application/pdf" and not is_locked(sent.data)
    txns = env.conn.execute("SELECT txn_date, direction, amount_paise, candidate_id FROM bank_txn ORDER BY txn_date"
                            ).fetchall()
    assert [(t[0], t[1], t[2], t[3] is not None) for t in txns] == [
        ("2026-10-12", "debit", 18_000_000, False),  # confirmed, not added again
        ("2026-10-13", "debit", 59_000, True),  # missing from the ledger: added
        ("2026-10-15", "credit", 26_000_000, True),
    ]
    acct = env.conn.execute("SELECT reported_balance_paise FROM bank_account WHERE id = 1").fetchone()
    assert acct[0] == 69_941_000  # the closing balance reached the drift check
    assert env.conn.execute("SELECT status FROM owner_question WHERE kind = 'unlock_pdf'").fetchone()[0] == "ANSWERED"


def test_the_password_never_reaches_the_db_the_trace_the_logs_or_a_job(web, caplog):
    caplog.set_level(logging.DEBUG)
    env, client = web
    doc_id, _ = upload_locked(env)
    csrf = login(client)
    wrong = PASSWORD + "-wrong"
    r = post(client, f"/documents/{doc_id}/unlock", csrf, {"password": wrong})
    assert r.status_code == 422 and "That password did not open the PDF" in r.text
    assert wrong not in r.text and doc_status(env, doc_id) == "LOCKED"
    assert post(client, f"/documents/{doc_id}/unlock", csrf, {"password": PASSWORD}).status_code == 303
    run_all(env, default_handlers(reads_statement()))
    env.conn.execute("PRAGMA wal_checkpoint(FULL)")
    for secret in (PASSWORD, wrong):
        needle = secret.encode()
        for f in Path(env.settings.database_path).parent.glob(Path(env.settings.database_path).name + "*"):
            assert needle not in f.read_bytes(), f.name
        for f in Path(env.settings.trace_dir).rglob("*"):
            assert not f.is_file() or needle not in f.read_bytes(), f.name
        assert secret not in caplog.text
        assert all(secret not in (e or "") for (e,) in env.conn.execute("SELECT last_error FROM job"))


def test_a_locked_attachment_on_a_bank_email_is_unlocked_inside_the_email(web):
    env, client = web
    msg = EmailMessage()
    msg["From"] = "HDFC Bank <alerts@hdfcbank.example>"
    msg["Date"] = "Fri, 16 Oct 2026 17:00:00 +0530"
    msg["Subject"] = "Your account statement"
    msg.set_content("Your statement is attached. It is protected with your password.")
    msg.add_attachment(locked_pdf(), maintype="application", subtype="pdf", filename="statement.pdf")
    (Path(env.settings.test_inbox_path) / "statement.eml").write_bytes(bytes(msg))
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    run_all(env, default_handlers(FakeBackend()))
    doc_id = env.conn.execute("SELECT id FROM source_document WHERE status = 'LOCKED'").fetchone()[0]
    csrf = login(client)
    assert post(client, f"/documents/{doc_id}/unlock", csrf, {"password": PASSWORD}).status_code == 303
    backend = reads_statement()
    run_all(env, default_handlers(backend))
    text, attached = backend.calls("StatementExtract")[0].contents[:2]
    assert "Your account statement" in text and not is_locked(attached.data)


def test_a_statement_that_does_not_add_up_writes_nothing_and_goes_to_the_owner(web):
    env, client = web
    doc_id, _ = upload_locked(env)
    login(client)
    bad = {**STATEMENT, "closing_balance_text": "Rs.7,00,000.00"}
    actions.unlock_document(env.conn, User(1, 1, "o", "owner"), doc_id, PASSWORD,
                            DocumentStore(env.settings.data_dir, env.settings.fernet_key), clock=env.clock)
    run_all(env, default_handlers(reads_statement(bad).queue("StatementExtract", bad, bad)))
    assert env.conn.execute("SELECT COUNT(*) FROM bank_txn").fetchone()[0] == 0
    body = env.conn.execute("SELECT body_text FROM owner_question WHERE kind = 'confirm_record'").fetchone()[0]
    assert body.startswith("A bank statement from an uploaded PDF could not be read reliably: statement_arithmetic")
    assert "Bank statement" in client.get("/attention").text


ACCOUNTS = [AccountIn(1, "4821", frozenset({"alerts@hdfcbank.example"}))]


def _x(**over):
    from app.ai.extract import StatementExtract

    return StatementExtract.model_validate({**STATEMENT, **over})


def test_statement_checks_in_pure_code():
    checks, rec, _ = check_statement(_x(), None, MailFacts(None, None), ACCOUNTS, lambda k: None)
    assert checks["statement_arithmetic"] == PASSED and rec.closing_paise == 69_941_000 and len(rec.rows) == 3
    checks, rec, _ = check_statement(_x(period_to="2026-10-14"), None, MailFacts(None, None), ACCOUNTS, lambda k: None)
    assert rec is None and checks["dates"].startswith("failed: rows dated 2026-10-15 are outside")
    checks, _, _ = check_statement(_x(), None, MailFacts("someone@example.test", None), ACCOUNTS, lambda k: None)
    assert checks["account"].startswith("failed: no single account")
    checks, _, _ = check_statement(_x(), None, MailFacts(None, None), ACCOUNTS, lambda k: 7)
    assert checks["duplicates"] == "failed: the same statement as candidate 7"
