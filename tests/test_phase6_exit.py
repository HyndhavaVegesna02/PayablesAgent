"""TDD Phase 6 exit (batch 5, CHG-007): "the photo, PDF, voice and duplicate
scenarios pass". Driven through the worker with the demo's fixture AI, so
the one copy of the canned replies (fixtures/ai_replies.json) and the
fixtures made by scripts/make_fixtures.py are what is tested.

- AC1: a password-protected statement PDF unlocks with a once-used,
  never-stored password and passes statement arithmetic
- AC2: a handwritten bill photo gives fields that pass the GSTIN and total checks
- AC3: a Hinglish voice note saying "dedh lakh" gives ₹1,50,000, transcript beside it
- AC4: the same invoice by email and by photo gives one payable
- AC5: a bill with different bank details marks the vendor change_pending,
  and only the owner can approve it
- AC6: the statement password reaches no database file, trace, log or job"""

import json
import logging
from pathlib import Path

import pytest

from app.ai.fixture_backend import FIXTURE_UPLOADS, FixtureBackend
from app.ingest.store import DocumentStore
from app.jobs import queue
from app.web import actions, repo
from app.web.auth import User
from app.web.routes.attention import prefill
from app.worker import default_handlers
from tests.web_helpers import login, make_web_env, post
from tests.worker_helpers import deliver, run_all

STATEMENT_PASSWORD = "SPW-4821-oct"  # as in scripts/make_fixtures.py
HELPER = User(2, 1, "helper@example.test", "helper")


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def at(env, day, hour):
    env.clock.advance(env.clock.now().replace(day=day, hour=hour, minute=0) - env.clock.now())


def work(env):
    run_all(env, default_handlers(FixtureBackend()))


def poll(env, *names):
    deliver(env, *names)
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    work(env)


def upload(env, name, kind):
    actions.upload(env.conn, HELPER, (FIXTURE_UPLOADS / name).read_bytes(), kind,
                   DocumentStore(env.settings.data_dir, env.settings.fernet_key), clock=env.clock)
    work(env)


def waiting(env, kind):
    return [c for c in repo.waiting_candidates(env.conn, 1) if c["document_kind"] == kind]


def confirm(client, csrf, env, cand):
    values = prefill(cand, repo.accounts(env.conn, 1))
    assert post(client, f"/candidates/{cand['id']}/confirm", csrf, values).status_code == 303


def test_ac4_and_ac5_one_invoice_by_email_and_photo_then_a_bank_change(web):
    env, client = web
    at(env, 13, 12)
    poll(env, "08-invoice-ashirwad-ap131.eml")
    (emailed,) = waiting(env, "email")
    upload(env, "ap-2610-131-photo.png", "photo")
    photo = env.conn.execute("SELECT status, checks_json FROM candidate ORDER BY id DESC").fetchone()
    assert photo[0] == "INVALID" and f"already waiting for the owner (entry {emailed['id']})" in photo[1]
    csrf = login(client)
    confirm(client, csrf, env, emailed)
    bills = env.conn.execute("SELECT amount_paise FROM payable WHERE invoice_number = 'AP/2610/131'").fetchall()
    assert [b[0] for b in bills] == [9_500_000]  # AC4: one payable
    vendor = env.conn.execute("SELECT * FROM party WHERE name = 'Ashirwad Paper Suppliers'").fetchone()
    assert (vendor["bank_account_mask"], vendor["bank_ifsc"], vendor["bank_status"]) == (
        "XXXX4410", "SBIN0001234", "verified")  # first details, from the bill the owner checked

    at(env, 14, 11)
    poll(env, "09-invoice-ashirwad-new-bank.eml")
    vendor = env.conn.execute("SELECT * FROM party WHERE name = 'Ashirwad Paper Suppliers'").fetchone()
    assert vendor["bank_status"] == "change_pending" and vendor["bank_account_mask"] == "XXXX4410"  # AC5
    page = client.get("/attention").text
    assert "Vendor bank details change pending: verify before paying" in page
    assert "SYSTEM NOTE" not in page  # the injected text never reaches the owner's screen


def test_ac2_a_handwritten_bill_passes_the_gstin_and_total_checks(web):
    env, client = web
    at(env, 14, 12)
    upload(env, "handwritten-bill-ganesh.png", "photo")
    (bill,) = waiting(env, "photo")
    assert bill["status"] == "VALID"
    assert (bill["checks"]["gstin"], bill["checks"]["invoice_arithmetic"]) == ("passed", "passed")
    confirm(client, login(client), env, bill)
    row = env.conn.execute("SELECT p.amount_paise, pt.name FROM payable p JOIN party pt ON pt.id = p.party_id "
                           "WHERE p.invoice_number = '418'").fetchone()
    assert tuple(row) == (1_239_000, "Shree Ganesh Hardware")


def test_ac3_dedh_lakh_said_in_a_voice_note_is_150000_with_the_transcript(web):
    env, client = web
    upload(env, "voice-note-ashirwad.wav", "voice")
    (note,) = waiting(env, "voice")
    assert note["record"]["amount_paise"] == 15_000_000 and "dedh lakh rupaye" in note["transcript"]
    login(client)
    page = client.get("/attention").text
    assert "What was said:" in page and 'value="₹1,50,000"' in page


def test_ac1_and_ac6_the_locked_statement_opens_once_and_the_password_goes_nowhere(web, caplog):
    caplog.set_level(logging.DEBUG)
    env, client = web
    at(env, 14, 9)
    poll(env, "10-statement-hdfc-locked.eml")
    doc_id = env.conn.execute("SELECT id FROM source_document WHERE status = 'LOCKED'").fetchone()[0]
    csrf = login(client)
    assert post(client, f"/documents/{doc_id}/unlock", csrf, {"password": "wrong"}).status_code == 422
    assert post(client, f"/documents/{doc_id}/unlock", csrf, {"password": STATEMENT_PASSWORD}).status_code == 303
    work(env)
    cand = env.conn.execute("SELECT status, checks_json FROM candidate WHERE record_type = 'statement'").fetchone()
    assert cand[0] == "VALID" and json.loads(cand[1])["statement_arithmetic"] == "passed"  # AC1
    acct = env.conn.execute("SELECT reported_balance_paise, drift_status FROM bank_account WHERE id = 1").fetchone()
    assert tuple(acct) == (47_241_000, "OK")  # three rows added; the ledger agrees with the bank
    env.conn.execute("PRAGMA wal_checkpoint(FULL)")
    needle = STATEMENT_PASSWORD.encode()
    db = Path(env.settings.database_path)
    for f in [*db.parent.glob(db.name + "*"), *Path(env.settings.trace_dir).rglob("*")]:
        assert not f.is_file() or needle not in f.read_bytes(), f.name  # AC6
    assert STATEMENT_PASSWORD not in caplog.text
    assert all(STATEMENT_PASSWORD not in (e or "") for (e,) in env.conn.execute("SELECT last_error FROM job"))
