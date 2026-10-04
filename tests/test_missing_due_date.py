"""A missing due date reaches the owner flagged, never as a value the form
refuses (batch 8, CHG-030; found by the live pilot, scenario 04). TDD
pipeline step 5: the owner fills the fields that still fail. A date that
wasn't on the document or said is never asked of the model again, which
would only invite a guess."""

import json

import pytest

from app.ai.client import RawAIResponse
from app.ai.extract import InvoiceExtract, VoiceBillExtract
from app.ai.fixture_backend import load_replies
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
SHARMA = load_replies("uploads")["voice-note-sharma.wav"]["VoiceBillExtract"]


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


SAID = {"fill": {"party": "Sharma Packaging", "amount": "1,50,000", "due_date": "2026-11-05"}}


def test_in_an_eval_a_form_refusal_of_what_was_read_is_an_extract_failure(monkeypatch):
    from app.ai.fixture_backend import FixtureBackend

    def refuse(conn, user, cid, values, *, clock):  # a value read from the document, which the owner left as read
        raise runner.actions.FieldErrors({"invoice_date": "Enter a date."}, values)

    monkeypatch.setattr(runner.actions, "confirm_candidate", refuse)
    r = runner.run_once(_scenario_04(SAID), FixtureBackend(), runner.load_config(None)[0])
    assert (r.status, r.component) == ("FAILED", "extract")
    assert r.error.startswith("the owner's form refused entry 1: invoice_date: ")


def test_a_marked_field_the_scenario_gives_no_value_for_is_the_scenarios_gap_not_the_models():
    from app.ai.fixture_backend import FixtureBackend

    r = runner.run_once(_scenario_04(True), FixtureBackend(), runner.load_config(None)[0])  # the date is marked
    assert (r.status, r.component) == ("FAILED", "crash")
    assert r.error == ("ScenarioGap: the page marks due_date on entry 1, and the scenario gives the owner no value "
                       "for it")


def test_a_real_exception_is_still_a_crash(monkeypatch):
    from app.ai.fixture_backend import FixtureBackend

    def boom(env, spec):
        raise RuntimeError("the app broke")

    monkeypatch.setitem(runner.STEPS, "confirm_waiting", boom)
    r = runner.run_once(_scenario_04(True), FixtureBackend(), runner.load_config(None)[0])
    assert (r.status, r.component, r.error) == ("FAILED", "crash", "RuntimeError: the app broke")


def test_the_scripted_owner_fills_only_what_the_page_marks(monkeypatch):
    """The step itself: `fill` reaches the form only for a field the page marks
    (the page's own rule, imported), never over a value that was read."""
    from app.ai.fixture_backend import FixtureBackend

    seen = []
    real = runner.actions.confirm_candidate
    monkeypatch.setattr(runner.actions, "confirm_candidate",
                        lambda conn, user, cid, values, *, clock: seen.append(values) or real(
                            conn, user, cid, values, clock=clock))

    class ReadsADate(FixtureBackend):
        def generate(self, *, model, system, contents, thinking, json_schema):
            if (json_schema or {}).get("title") == "VoiceBillExtract":
                return RawAIResponse(json.dumps({**SHARMA, "due_date": "2026-11-09"}), 0, 0, 0)
            return super().generate(model=model, system=system, contents=contents, thinking=thinking,
                                    json_schema=json_schema)

    s = scenario.load("04-hinglish-voice-note")
    r = runner.run_once(s, ReadsADate(), runner.load_config(None)[0])  # a date was read: nothing marked
    assert seen[-1]["due_date"] == "2026-11-09"  # the fill's 2026-11-05 never overwrites what was read
    assert [c.id for c in r.checks if not c.ok] == ["missing-due-date-flagged-not-guessed", "bill-due-as-the-owner-said"]
    seen.clear()
    r = runner.run_once(s, FixtureBackend(), runner.load_config(None)[0])  # no date read: marked, filled
    assert seen[-1]["due_date"] == "2026-11-05" and r.status == "PASSED"
    seen.clear()
    monkeypatch.setattr(runner, "flagged_fields", lambda c, shown: {})  # empty, but the page marks nothing
    runner.run_once(s, FixtureBackend(), runner.load_config(None)[0])
    assert seen[-1]["due_date"] == ""  # so the fill is not applied: only what the page marks is typed


def test_a_refusal_blames_extract_validate_or_nobody():
    assert runner.refusal_component({"due_date": "Enter a date."}, set()) == "extract"
    assert runner.refusal_component({"entry": "the same entry is already waiting"}, set()) == "validate"
    assert runner.refusal_component({"priority": "Choose a priority."}, set()) is None  # the app's own value
    assert runner.refusal_component({"due_date": "Enter a date."}, {"due_date"}) is None  # the owner typed it


def test_in_an_eval_a_rule_check_refusal_is_a_validate_failure(monkeypatch):
    from app.ai.fixture_backend import FixtureBackend

    def refuse(conn, user, cid, values, *, clock):
        raise runner.actions.FieldErrors({"entry": "the same entry is already waiting for confirmation"}, values)

    monkeypatch.setattr(runner.actions, "confirm_candidate", refuse)
    r = runner.run_once(_scenario_04({"fill": {"due_date": "2026-11-05"}}), FixtureBackend(),
                        runner.load_config(None)[0])
    assert (r.status, r.component) == ("FAILED", "validate")


def test_an_app_side_refusal_is_still_a_crash(monkeypatch):
    from app.ai.fixture_backend import FixtureBackend

    def refuse(conn, user, cid, values, *, clock):
        raise runner.actions.FieldErrors({"priority": "Choose a priority."}, values)

    monkeypatch.setattr(runner.actions, "confirm_candidate", refuse)
    r = runner.run_once(_scenario_04(SAID), FixtureBackend(), runner.load_config(None)[0])
    assert (r.status, r.component) == ("FAILED", "crash") and r.error.startswith("FieldErrors")
