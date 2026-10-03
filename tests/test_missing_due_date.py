"""A missing due date reaches the owner flagged, never as a value the form
refuses (batch 8, CHG-030; found by the live pilot, scenario 04). TDD
pipeline step 5: the owner fills the fields that still fail. A date that
wasn't on the document or said is never asked of the model again, which
would only invite a guess."""

import pytest

from app.ai.extract import InvoiceExtract, VoiceBillExtract
from app.validate import NO_DUE_DATE, failed
from app.validate.invoice import check_invoice
from app.validate.voice import check_voice
from app.web import actions, repo
from app.web.routes.attention import prefill
from evals import runner, scenario
from tests.test_bank_change import BILL
from tests.test_voice import NOTE, OWNER, send_note
from tests.web_helpers import login, make_web_env

FLAGGED = failed(NO_DUE_DATE)


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def test_a_voice_note_with_no_due_date_fails_the_dates_check_by_name():
    checks, record, reading = check_voice(VoiceBillExtract.model_validate({**NOTE, "due_date": None}), None,
                                          lambda key: None)
    assert checks["dates"] == FLAGGED and record is None and reading["due_date"] is None


def test_a_bill_with_no_due_date_fails_it_too_but_a_sales_invoice_does_not():
    bill = InvoiceExtract.model_validate({**BILL, "due_date": None})
    checks, record, reading = check_invoice(bill, None, "Saraswati Precision Works", lambda key: None)
    assert reading["kind"] == "bill" and checks["dates"] == FLAGGED and record is None
    sale = InvoiceExtract.model_validate({**BILL, "due_date": None, "seller_name": "Saraswati Precision Works",
                                          "seller_gstin": None, "buyer_name": "Nandi Foods"})
    checks, record, reading = check_invoice(sale, None, "Saraswati Precision Works", lambda key: None)
    assert reading["kind"] == "invoice" and checks["dates"] == "passed"


def test_it_goes_to_the_owner_after_one_reading_with_the_field_marked_empty(web):
    env, client = web
    backend = send_note(env, {**NOTE, "due_date": None})
    assert len(backend.calls("VoiceBillExtract")) == 1  # never asked again: that would invite a guess
    cand = next(c for c in repo.waiting_candidates(env.conn, 1) if c["document_kind"] == "voice")
    assert cand["status"] == "AWAITING_OWNER" and cand["checks"]["dates"] == FLAGGED
    assert prefill(cand, [])["due_date"] == ""
    login(client)
    page = client.get("/attention").text
    assert "Not given on the document: fill it in." in page
    values = {**prefill(cand, repo.accounts(env.conn, 1)), "due_date": "2026-10-30"}
    actions.confirm_candidate(env.conn, OWNER, cand["id"], values, clock=env.clock)
    assert env.conn.execute("SELECT due_date FROM payable WHERE invoice_number = 'AP/2610/150'").fetchone()[0] \
        == "2026-10-30"


def test_the_voice_prompt_says_never_to_guess_a_year():
    text = (runner.ROOT / "app" / "ai" / "prompts" / "extract_voice.v1.md").read_text(encoding="utf-8")
    assert "with its\n  year is said" in text and "Never guess a year or a date" in text


def _scenario_04(confirm_step):
    s = scenario.load("04-hinglish-voice-note")
    return s.model_copy(update={"steps": [s.steps[0], {"confirm_waiting": confirm_step}]})


def test_in_an_eval_a_form_refusal_of_what_was_read_is_an_extract_failure(tmp_path):
    from app.ai.fixture_backend import FixtureBackend

    r = runner.run_once(_scenario_04(True), FixtureBackend(), runner.load_config(None)[0])  # nobody fills the date
    assert (r.status, r.component) == ("FAILED", "extract")
    assert r.error.startswith("the owner's form refused entry 1 as it was read: due_date: ")


def test_a_real_exception_is_still_a_crash(monkeypatch):
    from app.ai.fixture_backend import FixtureBackend

    def boom(env, spec):
        raise RuntimeError("the app broke")

    monkeypatch.setitem(runner.STEPS, "confirm_waiting", boom)
    r = runner.run_once(_scenario_04(True), FixtureBackend(), runner.load_config(None)[0])
    assert (r.status, r.component, r.error) == ("FAILED", "crash", "RuntimeError: the app broke")


def test_the_scripted_owner_fills_only_what_the_entry_flags():
    assert runner.flagged_fields({"checks": {"dates": FLAGGED}}) == {"due_date"}
    assert runner.flagged_fields({"checks": {"dates": "passed"}}) == set()
