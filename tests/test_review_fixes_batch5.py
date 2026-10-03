"""Batch 5 review, round 1 (docs/batches/2026-10-03-5/review.md): one test
per finding fixed."""

import json
from pathlib import Path

import pytest

from app.domain.money import parse_spoken_inr
from app.ingest.store import DocumentStore
from app.web import actions, repo
from app.web.auth import User
from app.web.routes.attention import prefill
from app.worker import default_handlers
from tests.fake_ai import FakeBackend
from tests.test_bank_change import BILL, ON_RECORD, ashirwad, bank_question, deliver_bill
from tests.test_invoice_pipeline import FROM_PHOTO, INVOICE, PHOTO
from tests.test_pdf_unlock import STATEMENT, reads_statement, upload_locked
from tests.web_helpers import approve_form, login, make_web_env, plan_now, post
from tests.worker_helpers import run_all

OWNER = User(1, 1, "owner@example.test", "owner")
HELPER = User(2, 1, "helper@example.test", "helper")


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    env.conn.execute("UPDATE party SET bank_account_mask = ?, bank_ifsc = ?, bank_status = 'verified' "
                     "WHERE name = 'Ashirwad Paper Suppliers'", ON_RECORD)
    env.conn.commit()
    yield env, client
    env.conn.close()


def reads(reply, title="InvoiceExtract"):
    backend = FakeBackend()
    if title == "InvoiceExtract":
        backend.queue("SortResult", {"doc_type": "invoice", "reason": "an invoice"})
    return backend.queue(title, reply)


def upload(env, backend, content, kind="photo"):
    actions.upload(env.conn, HELPER, content, kind, DocumentStore(env.settings.data_dir, env.settings.fernet_key),
                   clock=env.clock)
    run_all(env, default_handlers(backend))


def candidate(env, cid):
    return next(c for c in repo.waiting_candidates(env.conn, 1) if c["id"] == cid)


def last_candidate_id(env):
    return env.conn.execute("SELECT MAX(id) FROM candidate").fetchone()[0]


# --- owner and ledger side -----------------------------------------------------------------


def test_c1_a_bill_confirmed_for_another_vendor_than_it_was_read_as_is_still_compared(web):
    env, _ = web
    # Read as a near-spelling no vendor matches, so the pipeline flags nothing...
    upload(env, reads({**BILL, "seller_name": "Ashirvad Papers", "seller_gstin": None, "gst_texts": [],
                       "total_text": "Rs.40,000.00"}), PHOTO)
    cid = last_candidate_id(env)
    assert ashirwad(env)["bank_status"] == "verified" and bank_question(env) is None
    # ...and the owner corrects the vendor on the confirm form.
    values = {**prefill(candidate(env, cid), []), "party": "Ashirwad Paper Suppliers"}
    actions.confirm_candidate(env.conn, OWNER, cid, values, clock=env.clock)
    p = ashirwad(env)
    assert p["bank_status"] == "change_pending" and (p["bank_account_mask"], p["bank_ifsc"]) == ON_RECORD
    q = bank_question(env)
    assert q["status"] == "OPEN" and json.loads(q["choices_json"]) == {"party_id": p["id"], "candidate_id": cid}


def test_m2_deciding_one_proposal_keeps_another_open_and_the_vendor_pending(web):
    env, client = web
    deliver_bill(env, BILL)  # proposes 9921 / HDFC0004567
    first = json.loads(bank_question(env)["choices_json"])["candidate_id"]
    upload(env, reads({**BILL, "invoice_number": "AP/2610/141", "payee_account_number": "60000 1234",
                       "payee_ifsc": "ICIC0001111"}), PHOTO + b" 141")
    second = last_candidate_id(env)
    party_id = ashirwad(env)["id"]
    csrf = login(client)
    assert post(client, f"/parties/{party_id}/bank-change", csrf,
                {"decision": "approve", "candidate_id": 99999}).status_code == 409  # not a pending proposal
    assert post(client, f"/parties/{party_id}/bank-change", csrf,
                {"decision": "approve", "candidate_id": first}).status_code == 303
    p = ashirwad(env)
    assert (p["bank_account_mask"], p["bank_ifsc"]) == ("XXXX9921", "HDFC0004567")
    assert p["bank_status"] == "change_pending"  # the second proposal still differs
    statuses = dict(env.conn.execute(
        "SELECT json_extract(choices_json, '$.candidate_id'), status FROM owner_question "
        "WHERE kind = 'approve_bank_change'").fetchall())
    assert statuses == {first: "ANSWERED", second: "OPEN"}
    assert post(client, f"/parties/{party_id}/bank-change", csrf,
                {"decision": "reject", "candidate_id": second}).status_code == 303
    p = ashirwad(env)
    assert (p["bank_account_mask"], p["bank_ifsc"], p["bank_status"]) == ("XXXX9921", "HDFC0004567", "verified")


def test_m3_the_confirm_card_shows_the_bank_details_the_bill_printed(web):
    env, client = web
    env.conn.execute("UPDATE party SET bank_account_mask = NULL, bank_ifsc = NULL, bank_status = 'none'")
    env.conn.commit()
    deliver_bill(env, BILL, body="Invoice AP/2610/140.")
    login(client)
    assert "Bank details on this bill:</strong> account ending 9921, IFSC HDFC0004567" in client.get("/attention").text


def test_the_d20_warning_shows_on_the_approved_rows_too(web):
    env, client = web
    plan_now(env)
    csrf = login(client)
    run_id, versions = approve_form(client.get("/").text)
    assert post(client, f"/plans/{run_id}/approve", csrf, versions).status_code == 303  # before any change
    deliver_bill(env, BILL)
    page = client.get("/").text
    awaiting = page.split("Approved, waiting to be paid")[1].split("</article>")[0]
    assert "Vendor bank details change pending: verify before paying" in awaiting


def test_an_overdue_missing_tax_amount_warns_and_a_given_amount_is_not_given_twice(web):
    from datetime import date

    from app.domain.models import TaxObligationNew
    from app.ledger import writer

    env, client = web
    plan_now(env)
    ob = writer.create_tax_obligation(
        TaxObligationNew(business_id=1, tax_type="TDS", period="2026-08", due_date=date(2026, 10, 7),
                         amount_paise=None, amount_status="MISSING"),
        actor="owner:1", reason="x", source_ref=None, conn=env.conn, clock=env.clock)
    env.conn.commit()
    login(client)
    assert "TDS 2026-08 amount missing (due Wed 07 Oct): plan may be optimistic" in client.get("/").text
    actions.supply_tax_amount(env.conn, OWNER, ob.id, {"amount": "5,000"}, clock=env.clock)
    with pytest.raises(actions.Refused):
        actions.supply_tax_amount(env.conn, OWNER, ob.id, {"amount": "6,000"}, clock=env.clock)


# --- document side ---------------------------------------------------------------------------


def test_doc_m1_confirming_a_photo_of_an_invoice_already_confirmed_is_refused(web):
    env, _ = web
    upload(env, reads(INVOICE), PHOTO)
    first = last_candidate_id(env)
    actions.confirm_candidate(env.conn, OWNER, first, prefill(candidate(env, first), []), clock=env.clock)
    # A second photo, read unsure (so it waits for the owner rather than being set aside)
    upload(env, reads({**FROM_PHOTO, "uncertain_fields": ["total_text"]}), PHOTO + b" again")
    second = last_candidate_id(env)
    with pytest.raises(actions.FieldErrors) as e:
        actions.confirm_candidate(env.conn, OWNER, second, prefill(candidate(env, second), []), clock=env.clock)
    assert "invoice AP/2610/131 is already recorded" in e.value.errors["entry"]
    assert env.conn.execute("SELECT COUNT(*) FROM payable WHERE invoice_number = 'AP/2610/131'").fetchone()[0] == 1


def test_doc_m1_a_typed_entry_of_an_invoice_waiting_from_email_is_refused(web):
    env, _ = web
    upload(env, reads(INVOICE), PHOTO)
    waiting = last_candidate_id(env)
    with pytest.raises(actions.FieldErrors) as e:
        actions.add_entry(env.conn, HELPER, {"kind": "bill", "party": "Ashirwad Paper", "amount": "95,000",
                                             "invoice_number": "AP-2610-131", "due_date": "2026-10-29"},
                          clock=env.clock)
    assert f"is already waiting for the owner (entry {waiting})" in e.value.errors["entry"]


@pytest.mark.parametrize("said", ["ek lakh pachaas", "do lakh chalis", "2 lakh 40", "dedh lakh do", "-50000",
                                  "minus pachaas hazaar"])
def test_doc_m2_an_ambiguous_or_negative_spoken_amount_is_refused(said):
    with pytest.raises(ValueError):
        parse_spoken_inr(said)


def test_doc_m2_a_bare_tail_after_hazaar_or_sau_still_reads():
    assert parse_spoken_inr("do hazaar pachaas") == 205_000
    assert parse_spoken_inr("ek lakh pachaas hazaar paanch sau") == 15_050_000


def test_doc_minor_a_voice_amount_must_be_words_the_transcript_holds(web):
    env, _ = web
    from tests.test_voice import NOTE, WAV

    upload(env, reads({**NOTE, "amount_spoken": "1,50,000"}, "VoiceBillExtract"), WAV, kind="voice")
    cand = next(c for c in repo.waiting_candidates(env.conn, 1) if c["document_kind"] == "voice")
    assert cand["status"] == "AWAITING_OWNER" and cand["record"]["amount_paise"] is None


def test_doc_m3_two_identical_statement_rows_are_two_transactions(web):
    env, client = web
    env.clock.advance(env.clock.now().replace(day=16, hour=18) - env.clock.now())
    doc_id, _ = upload_locked(env)
    charge = {"txn_date": "2026-10-13", "direction": "debit", "amount_text": "590.00",
              "counterparty": "SMS CHARGES", "reference": None}
    early = {"txn_date": "2026-10-11", "direction": "debit", "amount_text": "100.00",
             "counterparty": "BEFORE OPENING", "reference": None}
    stmt = {**STATEMENT, "period_from": "2026-10-11", "rows": [early, *STATEMENT["rows"], charge],
            "opening_balance_text": "Rs.6,20,100.00", "closing_balance_text": "Rs.6,98,820.00"}
    csrf = login(client)
    assert post(client, f"/documents/{doc_id}/unlock", csrf, {"password": "Zq7-statement-pw-4821"}).status_code == 303
    run_all(env, default_handlers(reads_statement(stmt)))
    charges = env.conn.execute("SELECT COUNT(*) FROM bank_txn WHERE amount_paise = 59000").fetchone()[0]
    assert charges == 2  # the two identical charges are two debits
    assert env.conn.execute("SELECT COUNT(*) FROM bank_txn WHERE txn_date = '2026-10-11'").fetchone()[0] == 0
    assert Path(env.settings.database_path).exists()


# --- round 2 ------------------------------------------------------------------------------


def test_r2_a_bill_read_as_one_vendor_and_confirmed_as_another_moves_the_question(web):
    env, client = web
    env.conn.execute("UPDATE party SET bank_account_mask = 'XXXX7777', bank_ifsc = 'UTIB0000777', "
                     "bank_status = 'verified' WHERE name = 'Prime Chem Industries'")
    env.conn.commit()
    deliver_bill(env, BILL)  # read as Ashirwad, whose details differ: Ashirwad pending, asked
    cid = json.loads(bank_question(env)["choices_json"])["candidate_id"]
    prime = env.conn.execute("SELECT id FROM party WHERE name = 'Prime Chem Industries'").fetchone()[0]
    values = {**prefill(candidate(env, cid), []), "party": "Prime Chem Industries"}
    actions.confirm_candidate(env.conn, OWNER, cid, values, clock=env.clock)
    a = ashirwad(env)
    assert (a["bank_account_mask"], a["bank_ifsc"], a["bank_status"]) == (*ON_RECORD, "verified")  # withdrawn
    open_q = [json.loads(c) for (c,) in env.conn.execute(
        "SELECT choices_json FROM owner_question WHERE kind = 'approve_bank_change' AND status = 'OPEN'")]
    assert open_q == [{"party_id": prime, "candidate_id": cid}]
    csrf = login(client)
    assert post(client, f"/parties/{prime}/bank-change", csrf,
                {"decision": "reject", "candidate_id": cid}).status_code == 303
    status = env.conn.execute("SELECT bank_status FROM party WHERE id = ?", (prime,)).fetchone()[0]
    assert status == "verified"


@pytest.mark.parametrize("said, paise", [("1 lakh 50000", 15_000_000), ("ek lakh 25000", 12_500_000)])
def test_r2_a_thousands_tail_after_lakh_still_reads(said, paise):
    assert parse_spoken_inr(said) == paise


def test_r2_the_transcript_match_ignores_punctuation():
    from app.ai.extract import VoiceBillExtract
    from app.validate.voice import check_voice
    from tests.test_voice import NOTE

    note = VoiceBillExtract.model_validate({**NOTE, "transcript": "Ashirwad ka bill, ek lakh, pachaas hazaar.",
                                            "amount_spoken": "ek lakh pachaas hazaar"})
    checks, rec, _ = check_voice(note, None, lambda key: None)
    assert checks["amount"] == "passed" and rec.record["amount_paise"] == 15_000_000



# --- round 3 ------------------------------------------------------------------------------


def test_r3_a_bill_confirmed_for_a_vendor_with_no_details_still_withdraws_the_other_question(web):
    env, _ = web
    deliver_bill(env, BILL)  # read as Ashirwad, whose details differ: Ashirwad pending, asked
    cid = json.loads(bank_question(env)["choices_json"])["candidate_id"]
    values = {**prefill(candidate(env, cid), []), "party": "Brand New Paper Mart"}  # created on confirm
    actions.confirm_candidate(env.conn, OWNER, cid, values, clock=env.clock)
    a = ashirwad(env)
    assert (a["bank_account_mask"], a["bank_ifsc"], a["bank_status"]) == (*ON_RECORD, "verified")
    assert env.conn.execute("SELECT COUNT(*) FROM owner_question WHERE kind = 'approve_bank_change' "
                            "AND status = 'OPEN'").fetchone()[0] == 0
    new = env.conn.execute("SELECT bank_account_mask, bank_status FROM party WHERE name = 'Brand New Paper Mart'"
                           ).fetchone()
    assert tuple(new) == ("XXXX9921", "verified")  # its first details, shown on the card the owner confirmed


def test_r3_a_part_of_a_spoken_figure_is_not_the_amount_said():
    from app.ai.extract import VoiceBillExtract
    from app.validate.voice import check_voice
    from tests.test_voice import NOTE

    note = VoiceBillExtract.model_validate({**NOTE, "transcript": "bill hai 1,50,000 ka",
                                            "amount_spoken": "50,000"})
    checks, rec, _ = check_voice(note, None, lambda key: None)
    assert rec is None and checks["amount"].startswith("failed")
