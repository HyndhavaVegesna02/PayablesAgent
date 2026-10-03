"""Invoices by email and by upload (batch 5 plan, S3; CHG-007 AC4): read,
checked in pure code, and confirmed by the owner. The same invoice arriving
by email and as a photo becomes one payable, whichever comes first."""

from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.ai.client import Part
from app.ai.extract import InvoiceExtract
from app.ingest.store import DocumentStore
from app.jobs import queue
from app.validate import NOT_APPLICABLE, PASSED
from app.validate.invoice import check_invoice
from app.web import actions, repo
from app.web.auth import User
from app.web.routes.attention import prefill
from app.worker import default_handlers
from tests.fake_ai import FakeBackend
from tests.worker_helpers import make_mail_env
from tests.worker_helpers import run_all as _run_all

BUSINESS = "Saraswati Precision Works"
OWNER = User(1, 1, "owner@example.test", "owner")
HELPER = User(2, 1, "helper@example.test", "helper")
PHOTO = b"\xff\xd8\xff\xe0 photo of Ashirwad invoice AP/2610/131"
PDF = b"%PDF-1.4 Ashirwad invoice AP/2610/131"

# Rs.50,000.00 + Rs.30,508.00 = 80,508.00; CGST and SGST 7,245.72 each = 94,999.44; round off +0.56 = 95,000.00
INVOICE = {
    "seller_name": "Ashirwad Paper Suppliers", "seller_gstin": "27ZZZFZ0001Z1ZU",
    "buyer_name": "Saraswati Precision Works", "buyer_gstin": "27ZZZCZ0004Z1ZX",
    "invoice_number": "AP/2610/131", "invoice_date": "2026-10-14", "due_date": "2026-10-29",
    "lines": [{"description": "Kraft paper 120 GSM", "amount_text": "Rs.50,000.00"},
              {"description": "Duplex board", "amount_text": "Rs.30,508.00"}],
    "gst_texts": ["Rs.7,245.72", "Rs.7,245.72"], "round_off_text": "+0.56", "total_text": "Rs.95,000.00",
    "payee_account_number": None, "payee_ifsc": None, "uncertain_fields": [],
}
# The handwritten copy: no GSTIN legible, the vendor's short name.
FROM_PHOTO = {**INVOICE, "seller_name": "Ashirwad Paper", "seller_gstin": None, "buyer_gstin": None,
              "gst_texts": [], "lines": [], "round_off_text": None}


def x(**over):
    return InvoiceExtract.model_validate({**INVOICE, **over})


def nothing(_key):
    return None


# --- the checks, in pure code ---------------------------------------------------------


def test_a_vendor_bill_passes_every_check_and_reads_as_a_bill():
    checks, rec, reading = check_invoice(x(), None, BUSINESS, nothing)
    assert {k: v for k, v in checks.items() if v != NOT_APPLICABLE} == {
        "schema": PASSED, "amount": PASSED, "gstin": PASSED, "invoice_arithmetic": PASSED, "dates": PASSED,
        "duplicates": PASSED, "confidence": PASSED}
    assert rec.kind == "bill" and reading == rec.record == {
        "kind": "bill", "party": "Ashirwad Paper Suppliers", "invoice_number": "AP/2610/131",
        "invoice_date": "2026-10-14", "amount_paise": 9_500_000, "due_date": "2026-10-29", "priority": "normal"}


def test_our_own_invoice_reads_as_a_sales_invoice_to_the_buyer():
    _, rec, _ = check_invoice(x(seller_name="Saraswati Precision Works Pvt Ltd", buyer_name="Nandi Foods",
                                seller_gstin="27ZZZCZ0004Z1ZX", buyer_gstin=None), None, BUSINESS, nothing)
    assert rec.kind == "invoice" and rec.record["party"] == "Nandi Foods"
    assert rec.record["confidence"] == "EXPECTED" and "priority" not in rec.record


def test_an_invoice_neither_from_nor_to_the_business_goes_to_the_owner():
    checks, rec, _ = check_invoice(x(buyer_name="Someone Else Traders", buyer_gstin=None), None, BUSINESS, nothing)
    assert rec is None and "whether this is a bill or a sales invoice" in checks["confidence"]


def test_a_bad_gstin_fails():
    checks, rec, _ = check_invoice(x(seller_gstin="27ZZZFZ0001Z1ZA"), None, BUSINESS, nothing)
    assert rec is None and checks["gstin"] == "failed: 27ZZZFZ0001Z1ZA: check character should be U"


def test_gst_charged_with_no_readable_seller_gstin_fails():
    checks, _, _ = check_invoice(x(seller_gstin=None), None, BUSINESS, nothing)
    assert checks["gstin"] == "failed: the GSTIN could not be read"


def test_a_round_off_beyond_one_rupee_fails_the_arithmetic():
    checks, rec, _ = check_invoice(x(round_off_text="+1.50", total_text="Rs.95,000.94"), None, BUSINESS, nothing)
    assert rec is None and checks["invoice_arithmetic"] == "failed: the round-off of ₹1.50 is more than ₹1"


def test_a_negative_round_off_is_read_with_its_sign():
    checks, rec, _ = check_invoice(x(round_off_text="(-) 0.44", total_text="Rs.94,999.00"), None, BUSINESS, nothing)
    assert checks["invoice_arithmetic"] == PASSED and rec is not None


def test_an_unreadable_total_fails_amount_and_skips_the_arithmetic():
    checks, rec, reading = check_invoice(x(total_text="ninety five"), None, BUSINESS, nothing)
    assert rec is None and checks["amount"].startswith("failed: total 'ninety five'")
    assert checks["invoice_arithmetic"].startswith("skipped") and reading["amount_paise"] is None


def test_a_duplicate_is_named_by_the_lookup():
    seen = []
    checks, rec, _ = check_invoice(x(), None, BUSINESS, lambda key: seen.append(key) or "it is already recorded")
    assert rec is None and checks["duplicates"] == "failed: it is already recorded"
    assert (seen[0].invoice_number, seen[0].party_gstin, seen[0].amount_paise) == ("AP2610131", "27ZZZFZ0001Z1ZU",
                                                                                   9_500_000)


# --- through the worker: email and photo become one payable ------------------------------


@pytest.fixture
def env(tmp_path):
    e = make_mail_env(tmp_path)
    e.settings = e.settings.model_copy(update={"fernet_key": Fernet.generate_key().decode()})
    e.clock.advance(timedelta(days=2, hours=3))  # Wed 14 Oct, 12:00
    yield e
    e.conn.close()


def _email(env, name="invoice-ap-131.eml"):
    msg = EmailMessage()
    msg["From"] = "Ashirwad Paper Suppliers <accounts@ashirwadpaper.example>"
    msg["To"] = "owner@example.test"
    msg["Date"] = "Wed, 14 Oct 2026 10:15:00 +0530"
    msg["Subject"] = "Invoice AP/2610/131"
    msg["Message-ID"] = "<ap-2610-131@ashirwadpaper.example>"
    msg.set_content("Dear Sir, please find our invoice AP/2610/131 attached.")
    msg.add_attachment(PDF, maintype="application", subtype="pdf", filename="AP-2610-131.pdf")
    (Path(env.settings.test_inbox_path) / name).write_bytes(bytes(msg))


def _poll(env, backend):
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    _run_all(env, default_handlers(backend))


def _upload(env, backend, content=PHOTO, user=HELPER):
    store = DocumentStore(env.settings.data_dir, env.settings.fernet_key)
    actions.upload(env.conn, user, content, "photo", store, clock=env.clock)
    _run_all(env, default_handlers(backend))


def _reads(reply):
    return FakeBackend().queue("SortResult", {"doc_type": "invoice", "reason": "an invoice"}).queue(
        "InvoiceExtract", reply)


def _candidates(env):
    return env.conn.execute("SELECT id, record_type, status, checks_json FROM candidate ORDER BY id").fetchall()


def _ap131(env):
    return env.conn.execute("SELECT id, status, amount_paise FROM payable WHERE invoice_number = 'AP/2610/131'").fetchall()


def _confirm(env, candidate_id):
    c = next(c for c in repo.waiting_candidates(env.conn, 1) if c["id"] == candidate_id)
    actions.confirm_candidate(env.conn, OWNER, candidate_id, prefill(c, repo.accounts(env.conn, 1)), clock=env.clock)


def test_an_emailed_invoice_with_its_pdf_waits_for_the_owner_then_becomes_a_confirmed_bill(env):
    _email(env)
    backend = _reads(INVOICE)
    _poll(env, backend)
    sent = backend.calls("InvoiceExtract")[0].contents
    assert isinstance(sent[0], str) and "Invoice AP/2610/131" in sent[0]
    assert sent[1] == Part("application/pdf", PDF)  # the attachment goes to the model as a file
    ((cid, record_type, status, _),) = _candidates(env)
    assert (record_type, status) == ("payable", "VALID") and _ap131(env) == []  # nothing until the owner checks it
    q = env.conn.execute("SELECT kind, body_text FROM owner_question WHERE status = 'OPEN' ORDER BY id DESC").fetchone()
    assert q[0] == "confirm_record"
    assert q[1] == ('Please check this bill from the email "Invoice AP/2610/131": Ashirwad Paper Suppliers, '
                    '₹95,000.')
    assert cid in {c["id"] for c in repo.waiting_candidates(env.conn, 1)}
    _confirm(env, cid)
    assert [(s, a) for _, s, a in _ap131(env)] == [("CONFIRMED", 9_500_000)]


def test_email_first_then_the_photo_is_a_duplicate_waiting_for_the_owner(env):
    _email(env)
    _poll(env, _reads(INVOICE))
    photo = _reads(FROM_PHOTO)
    _upload(env, photo)
    assert photo.calls("InvoiceExtract")[0].contents[-1] == Part("image/jpeg", PHOTO)
    first, second = _candidates(env)
    assert second[2] == "INVALID"
    assert f"is already waiting for the owner (entry {first[0]})" in second[3]
    _confirm(env, first[0])
    assert len(_ap131(env)) == 1


def test_photo_first_and_confirmed_then_the_email_is_a_duplicate_of_the_bill(env):
    _upload(env, _reads(FROM_PHOTO))
    ((cid, _, status, _),) = _candidates(env)
    assert status == "VALID"
    _confirm(env, cid)
    _email(env)
    _poll(env, _reads(INVOICE))
    assert _candidates(env)[-1][2] == "INVALID" and "Ashirwad Paper invoice AP/2610/131 is already recorded" in \
        _candidates(env)[-1][3]
    assert len(_ap131(env)) == 1


def test_a_reading_the_model_is_unsure_of_goes_to_the_owner_with_the_failing_check(env):
    _upload(env, _reads({**INVOICE, "uncertain_fields": ["total_text"]}))
    ((cid, _, status, _),) = _candidates(env)
    assert status == "AWAITING_OWNER"
    body = env.conn.execute("SELECT body_text FROM owner_question WHERE status = 'OPEN' ORDER BY id DESC").fetchone()[0]
    assert body.startswith("Please check this bill from an uploaded photo: Ashirwad Paper Suppliers, ₹95,000.")
    assert "confidence (the model is unsure of total_text)" in body
    assert repo.submissions(env.conn, 1, user_id=HELPER.id)[0]["status_text"] == "Waiting for the owner to confirm"


def test_an_upload_that_is_not_a_readable_file_is_never_sent_to_the_model(env):
    backend = FakeBackend()
    _upload(env, backend, content=b"plain text pretending to be a photo")
    assert backend.requests == []
    status, error = env.conn.execute("SELECT status, last_error FROM job WHERE kind = 'process_document'").fetchone()
    assert status == "dead" and "not a photo, PDF or voice note the model can read" in error


def test_without_an_invoice_number_the_same_party_amount_and_date_is_a_duplicate(env):
    unnumbered = {**FROM_PHOTO, "invoice_number": None}
    _upload(env, _reads(unnumbered))
    _upload(env, _reads({**unnumbered, "seller_name": "ASHIRWAD PAPER SUPPLIERS"}), content=PHOTO + b" again")
    first, second = _candidates(env)
    assert first[2] == "VALID" and second[2] == "INVALID"
    assert "Ashirwad Paper invoice of 2026-10-14 is already waiting for the owner" in second[3]
    _upload(env, _reads({**unnumbered, "invoice_date": "2026-10-15"}), content=PHOTO + b" next day")
    assert _candidates(env)[-1][2] == "VALID"  # another day: another bill
