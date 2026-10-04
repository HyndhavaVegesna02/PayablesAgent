"""Batch 8 review, fix round 1 (app): what the reviewer found, each pinned."""

import json
import re
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.agent.tools import schema_problems
from app.ai.extract import BankAlertExtract, InvoiceExtract, InvoiceLine
from app.config import MatchingConfig
from app.ingest.eml_folder import EmlFolderSource
from app.web import actions, repo
from app.web.routes.attention import prefill
from evals import runner
from tests import test_bank_change as bank
from tests.test_voice import NOTE, OWNER, WAV, send_note
from tests.web_helpers import make_web_env


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    env.conn.execute("UPDATE party SET bank_account_mask = ?, bank_ifsc = ?, bank_status = 'verified' "
                     "WHERE name = 'Ashirwad Paper Suppliers'", bank.ON_RECORD)
    env.conn.commit()
    yield env, client
    env.conn.close()


def _waiting(env, kind):
    return [c for c in repo.waiting_candidates(env.conn, 1) if c["document_kind"] == kind]


# --- M1: a repeat with no due date is still a duplicate ------------------------------------------


def test_a_repeated_voice_note_with_no_due_date_is_caught_as_a_duplicate(web):
    env, _ = web
    send_note(env, NOTE)
    (first,) = _waiting(env, "voice")
    actions.confirm_candidate(env.conn, OWNER, first["id"], prefill(first, []), clock=env.clock)
    backend = send_note(env, {**NOTE, "due_date": None}, content=WAV + b" said again")
    assert len(backend.calls("VoiceBillExtract")) == 1
    second = env.conn.execute("SELECT status, checks_json FROM candidate ORDER BY id DESC").fetchone()
    assert second["status"] == "INVALID" and json.loads(second["checks_json"])["duplicates"].startswith("failed")
    assert _waiting(env, "voice") == []  # the owner isn't asked to fill a date in a bill already recorded


def test_a_re_sent_invoice_with_no_due_date_is_caught_as_a_duplicate(web):
    env, _ = web
    bank.deliver_bill(env, {**bank.BILL, "due_date": None}, body="Invoice AP/2610/140.")
    (first,) = _waiting(env, "email")
    assert first["status"] == "AWAITING_OWNER" and first["checks"]["dates"] == "failed: no due date was given: fill it in"
    actions.confirm_candidate(env.conn, OWNER, first["id"], {**prefill(first, []), "due_date": "2026-10-27"},
                              clock=env.clock)
    env.clock.advance(timedelta(hours=1))
    bank.deliver_bill(env, {**bank.BILL, "due_date": None}, body="Invoice AP/2610/140 again.", ref="ap-140-again")
    again = env.conn.execute("SELECT status FROM candidate ORDER BY id DESC").fetchone()[0]
    assert again == "INVALID" and _waiting(env, "email") == []


def test_an_emailed_bill_with_no_due_date_goes_to_the_owner_after_one_reading(web):
    env, _ = web
    bank.deliver_bill(env, {**bank.BILL, "due_date": None}, body="Invoice AP/2610/140.")
    (c,) = _waiting(env, "email")
    assert (c["status"], c["checks"]["dates"], c["attempts"]) == ("AWAITING_OWNER", "failed: no due date was given: "
                                                                  "fill it in", 1)


# --- M2: a nested schema error names its own path -----------------------------------------------


def test_a_nested_schema_error_names_its_path_and_the_nested_records_fields():
    for line, want in (({"description": "Kraft paper"}, "missing lines.0.amount_text"),
                       ({"description": "x", "amount_text": "Rs.1.00", "qty": 2}, "not fields of this record: "
                                                                                    "lines.0.qty")):
        with pytest.raises(ValidationError) as e:
            InvoiceExtract.model_validate({**bank.BILL, "lines": [line]})
        text = schema_problems(e.value, InvoiceExtract)
        assert text.startswith(want) and text.endswith("; each of lines has: description, amount_text"), text


# --- M3: the prompt's field lists equal the schemas, both ways -----------------------------------


def _bullet(text, name):
    block = re.search(rf"  - {name}: (.*?)(?:\n  - |\n- |\n\n)", text, re.S).group(1)
    inner = re.findall(r"\{([^}]*)\}", block)
    flat = re.sub(r"\([^)]*\)", "", " ".join(block.split()))
    return {w.strip(" .") for w in flat.split(",") if w.strip(" .")}, inner


def test_the_prompts_field_lists_are_exactly_the_schemas():
    text = (runner.ROOT / "app" / "ai" / "prompts" / "exception_agent.v1.md").read_text(encoding="utf-8")
    alert, _ = _bullet(text, "bank_alert")
    invoice, inner = _bullet(text, "invoice")
    assert alert == set(BankAlertExtract.model_fields)
    assert invoice == set(InvoiceExtract.model_fields)
    assert [{w.strip() for w in i.split(",")} for i in inner] == [set(InvoiceLine.model_fields)]


# --- M4: a found invoice with no due date is still evidence --------------------------------------


@pytest.fixture
def mail(tmp_path):
    from tests.worker_helpers import make_mail_env

    e = make_mail_env(tmp_path)
    e.clock.advance(timedelta(days=2, hours=3))
    yield e
    e.conn.close()


def test_a_found_invoice_with_no_due_date_is_valid_evidence_and_the_owner_fills_the_date(mail):
    from tests.agent_helpers import open_unknown_debit_case
    from tests.test_run_case_job import BILL_09, final, run, step
    from tests.worker_helpers import deliver

    deliver(mail, "09-invoice-ashirwad-new-bank.eml")
    cid, msg = open_unknown_debit_case(mail), "09-invoice-ashirwad-new-bank.eml"
    case = run(mail, cid, step("look", "search_gmail", {"query": "AP/2610/140"}),
               step("propose", "add_candidate", {"record_type": "invoice", "message_id": msg,
                                                 "fields": {**BILL_09, "due_date": None}}),
               step("done", final=final(summary="The debit paid AP/2610/140.", cited=[msg], relied=[1])))
    assert case.status == "RESOLVED" and case.validation_failures == 0
    assert case.state["candidates"]["1"]["status"] == "VALID"


# --- minors ---------------------------------------------------------------------------------------


def test_a_found_invoice_with_a_check_skipped_is_not_made_valid_by_the_missing_date_rule(mail):
    from tests.agent_helpers import open_unknown_debit_case
    from tests.test_run_case_job import BILL_09, final, run, step
    from tests.worker_helpers import deliver

    deliver(mail, "09-invoice-ashirwad-new-bank.eml")
    cid, msg = open_unknown_debit_case(mail), "09-invoice-ashirwad-new-bank.eml"
    case = run(mail, cid, step("look", "search_gmail", {"query": "AP/2610/140"}),
               step("propose", "add_candidate", {"record_type": "invoice", "message_id": msg,
                                                 "fields": {**BILL_09, "due_date": None, "seller_name": ""}}),
               step("give up", final=final("NEEDS_OWNER", "Not sure.")))
    assert case.state["candidates"]["1"]["status"] == "INVALID"  # duplicates was skipped: not every check ran


def test_a_line_that_isnt_a_record_gets_the_lines_fields_too():
    with pytest.raises(ValidationError) as e:
        InvoiceExtract.model_validate({**bank.BILL, "lines": ["Kraft paper Rs.40,000.00"]})
    assert schema_problems(e.value, InvoiceExtract).endswith("; each of lines has: description, amount_text")


def test_a_first_ifsc_beside_an_account_on_record_is_asked_as_new_details():
    from app.validate.bank import change_question

    text = change_question("Ashirwad", "XXXX4410", None, "4410", "SBIN0001234")
    assert text.startswith("A bill from Ashirwad gives new bank details: account ending 4410, IFSC SBIN0001234 "
                           "(on record: account ending 4410).")


def test_a_first_account_number_at_an_ifsc_already_on_record_is_flagged(web):
    env, _ = web
    env.conn.execute("UPDATE party SET bank_account_mask = NULL, bank_ifsc = 'HDFC0004567', bank_status = 'verified' "
                     "WHERE name = 'Ashirwad Paper Suppliers'")
    env.conn.commit()
    bank.deliver_bill(env, bank.BILL, body="Invoice AP/2610/140.")  # the same IFSC, an account for the first time
    p = bank.ashirwad(env)
    assert (p["bank_account_mask"], p["bank_status"]) == (None, "change_pending")


def test_rejecting_an_entry_withdraws_the_bank_details_it_gave(web):
    env, _ = web
    env.conn.execute("UPDATE party SET bank_account_mask = NULL, bank_ifsc = NULL, bank_status = 'none' "
                     "WHERE name = 'Ashirwad Paper Suppliers'")
    env.conn.commit()
    bank.deliver_bill(env, bank.BILL, body="Invoice AP/2610/140.")
    (c,) = _waiting(env, "email")
    actions.reject_candidate(env.conn, OWNER, c["id"], clock=env.clock)
    q = bank.bank_question(env)
    assert q["status"] == "ANSWERED" and json.loads(q["answer_json"])["decision"].startswith("withdrawn")
    assert bank.ashirwad(env)["bank_status"] == "none"  # its real bills need no tick for a fake's account


def test_a_tax_type_that_doesnt_exist_is_refused_in_the_config():
    with pytest.raises(ValidationError):
        MatchingConfig(window_days=3, statutory_payees={"PFF": ["EPFO"]})


def test_gmails_unpadded_dates_work_in_the_folder_search():
    from tests.test_eml_folder import INBOX, at

    source = EmlFolderSource(INBOX, at(31))
    assert source.search("ashirwad paper after:2026/10/1") == source.search("ashirwad paper")


def test_an_opening_balance_day_is_the_day_the_facts_show():
    from app.ledger.reconcile import _since

    assert _since({"last_reconciled_at": None, "opening_balance_at": "2026-10-12"}) == "2026-10-12"
    assert _since({"last_reconciled_at": "2026-10-13T20:00:00+00:00", "opening_balance_at": "2026-10-12"}) \
        == "2026-10-14"  # 01:30 IST on the 14th


def test_the_bare_harness_is_told_the_owners_new_steps_in_words(tmp_path):
    """D24: the bare harness gets the owner's actions as sentences, the new ones too."""
    from app.clock import FakeClock
    from evals import bare, scenario
    from evals.runner import START, fresh_world

    s = scenario.load("09-vendor-email-changes-bank-details")
    s = s.model_copy(update={"steps": [{"confirm_waiting": {"fill": {"due_date": "2026-11-05"}}},
                                       {"approve_bank_details": {"invoice": "AP/2610/131"}}]})
    clock = FakeClock(START)
    conn = fresh_world(tmp_path / "bare.db", clock)
    try:
        out = bare._events(bare.BareEnv(conn, clock), s)
    finally:
        conn.close()
    assert "Where an entry has no due date, the owner fills in 2026-11-05." in out
    assert "The owner has checked by phone and approves the bank details on invoice AP/2610/131." in out


# --- batch 10, CHG-034 (PO D28): every empty required field is marked, and the owner fills each one ----------


def test_every_empty_required_field_is_marked_for_the_owner():
    from app.web.routes.attention import flagged_fields

    bill = {"record_type": "payable", "checks": {"dates": "failed: no due date was given: fill it in"}}
    assert flagged_fields(bill, {"party": "Sharma Packaging", "amount": "", "due_date": ""}) == {
        "amount": "Not read from the document: fill it in.", "due_date": "Not given on the document: fill it in."}
    missed = {"record_type": "payable", "checks": {"dates": "passed"}}  # the document gave one; it wasn't read
    assert flagged_fields(missed, {"party": "x", "amount": "₹1", "due_date": ""}) == {
        "due_date": "Not read from the document: fill it in."}
    assert flagged_fields({"record_type": "receivable"}, {"party": "", "amount": "₹1,000"}) == {
        "party": "Not read from the document: fill it in."}
    assert flagged_fields(bill, {"party": "x", "amount": "₹1", "due_date": "2026-11-05"}) == {}


def test_the_live_runs_unread_amount_is_marked_and_the_scripted_owner_types_what_was_said(monkeypatch):
    """Scenario 04, run 4 (docs/evals/2026-10-04-live-baseline): the model's amount couldn't be read. The page
    now marks the amount, and the scripted owner types the amount said in the note, so the run ends on the
    model's own reading (extract), not on a form refusal."""
    import json as _json

    from app.ai.client import RawAIResponse
    from app.ai.fixture_backend import FixtureBackend, load_replies
    from evals import scenario

    note = load_replies("uploads")["voice-note-sharma.wav"]["VoiceBillExtract"]

    class Misheard(FixtureBackend):
        def generate(self, *, model, system, contents, thinking, json_schema):
            if (json_schema or {}).get("title") == "VoiceBillExtract":
                return RawAIResponse(_json.dumps({**note, "amount_spoken": "dedh lakh kuch"}), 0, 0, 0)
            return super().generate(model=model, system=system, contents=contents, thinking=thinking,
                                    json_schema=json_schema)

    seen = []
    real = runner.actions.confirm_candidate
    monkeypatch.setattr(runner.actions, "confirm_candidate",
                        lambda conn, user, cid, values, *, clock: seen.append(values) or real(
                            conn, user, cid, values, clock=clock))
    r = runner.run_once(scenario.load("04-hinglish-voice-note"), Misheard(), runner.load_config(None)[0])
    assert seen[-1]["amount"] == "1,50,000" and seen[-1]["due_date"] == "2026-11-05"
    assert r.error is None and r.component == "extract"  # its own reading failed; the owner's typing didn't
    assert {c.id for c in r.checks if not c.ok} == {"amount-is-150000", "amount-checked-against-the-words"}


# --- batch 10 review, round 1 ----------------------------------------------------------------------------------


def test_every_scenario_that_confirms_states_what_its_documents_say():
    """D28.2: the scripted owner types every marked field from the document, so each confirming scenario states
    the values; otherwise a live misread would end as a ScenarioGap (a crash), not the model's own failure."""
    from evals import scenario

    for name in scenario.names():
        for step in scenario.load(name).steps:
            if "confirm_waiting" in step:
                fill = step["confirm_waiting"].get("fill", {}) if isinstance(step["confirm_waiting"], dict) else {}
                assert {"party", "amount", "due_date"} <= set(fill), name


@pytest.mark.parametrize("said", ["dedh lakh rupaya", "dedh lakh rupaiya", "dedh lakh rupye", "dedh lakh rupiya only"])
def test_the_common_spellings_of_rupaye_are_noise_too(said):
    from app.domain.money import parse_spoken_inr

    assert parse_spoken_inr(said) == 15_000_000


def test_combine_takes_the_latest_by_date_keeps_finished_runs_over_errored_ones_and_needs_two_parts():
    import copy

    from evals import report

    first = json.loads((runner.ROOT / "docs" / "evals" / "2026-10-04-live-baseline" / "report.json").read_text(
        encoding="utf-8"))
    later = copy.deepcopy(first)
    later["meta"]["date"] = "2026-10-05T09:00:00+05:30"
    for r in later["scenarios"]:
        r.update(errored=r["runs"], passed=0, failed=0)  # every run errored here
    later["scenarios"][0]["errored"] = 0  # but 01 finished
    combined = report.combine([("later", later), ("first", first)], "x")  # given out of order
    sources = {r["scenario"]: r["source"] for r in combined["scenarios"]}
    assert sources["01-debit-alert-for-a-planned-payment"] == "later"
    assert sources["02-password-protected-statement"] == "first"  # errored runs don't replace finished ones
    with pytest.raises(ValueError):
        report.combine([("first", first)], "x")


def test_check_evidence_names_a_combined_reports_missing_source(tmp_path, monkeypatch, capsys):
    from scripts import check_evidence

    evals = tmp_path / "docs" / "evals" / "2026-10-05-live-x"
    evals.mkdir(parents=True)
    (evals / "report.json").write_text(json.dumps({"meta": {"kind": "combined", "label": "x", "sources": [
        {"report": "2026-10-04-gone"}]}}), encoding="utf-8")
    monkeypatch.setattr(check_evidence, "ROOT", tmp_path)
    monkeypatch.setattr(check_evidence, "EVALS", tmp_path / "docs" / "evals")
    assert check_evidence.main() == 1
    assert "its sources ['2026-10-04-gone'] are not under docs/evals/" in capsys.readouterr().out

