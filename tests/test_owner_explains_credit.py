"""The owner says which invoice a credit paid (batch 21, CHG-057), the mirror
of the debit side (CHG-022). A credit the reconciler can't match raises an
explain_credit question built by code; the owner answers it on Needs
attention through /questions/{id}/answer. Linking matches the credit and
confirms the receivable as the owner; a different amount is stated in the
event, never edited into the receivable."""

import json
from datetime import date

import pytest

from app.ledger import writer
from app.ledger.reconcile import match_credit
from app.domain.models import ReceivableNew
from app.domain.states import TransitionRefused
from app.ledger.writer import EntityRef
from tests.reconcile_helpers import KAVERI, NANDI, txn
from tests.web_helpers import (
    HELPER,
    add_second_business,
    current_run,
    last_event_id,
    login,
    make_web_env,
    owner_events,
    plan_now,
    post,
)

OCT = lambda d: date(2026, 10, d)  # noqa: E731


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _credit(env, paise, payer, reference=None, day=13):
    t = txn(env, "credit", paise, OCT(day), payer, reference)
    with writer.atomic(env.conn):  # as the reconcile_txn job runs it
        result = match_credit(env.conn, t, window_days=3, clock=env.clock)
    return t, result


def _question(env, t):
    return env.conn.execute("SELECT * FROM owner_question WHERE kind = 'explain_credit' "
                            "AND json_extract(choices_json, '$.bank_txn_id') = ?", (t,)).fetchone()


def _rx(env, rid):
    return env.conn.execute("SELECT confidence, matched_txn_id, amount_paise, version FROM receivable WHERE id = ?",
                            (rid,)).fetchone()


def _answer(client, csrf, env, q, rid=None, **extra):
    data = {"decision": "invoice", **extra}
    if rid is not None:
        data.update({"receivable_id": str(rid), f"version_{rid}": str(_rx(env, rid)["version"])})
    return post(client, f"/questions/{q['id']}/answer", csrf, data)


def _status(env, table, row_id):
    col = "confidence" if table == "receivable" else "status"
    return env.conn.execute(f"SELECT {col} FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]


def _reasons(env, event_type):
    return [r[0] for r in env.conn.execute("SELECT reason FROM event WHERE event_type = ? ORDER BY id",
                                           (event_type,))]


# --- the question --------------------------------------------------------------------


def test_a_credit_from_no_known_payer_raises_one_question_offering_every_open_invoice(web):
    env, _, _ = web
    t, result = _credit(env, 15_000_000, "RAVI K (ravi.k@okaxis)", "UPI123")
    q = _question(env, t)
    assert q["case_id"] == result.case_ids[0]
    assert json.loads(q["choices_json"]) == {"case_id": result.case_ids[0], "bank_txn_id": t,
                                             "receivable_ids": [KAVERI, NANDI]}
    assert q["body_text"] == ("A ₹1,50,000 credit on Tue 13 Oct from RAVI K (ravi.k@okaxis) (reference UPI123) was "
                              "not matched to an invoice. Which invoice did it pay, if any?")
    with writer.atomic(env.conn):  # the job ran twice: still one question
        match_credit(env.conn, t, window_days=3, clock=env.clock)
    assert env.conn.execute("SELECT COUNT(*) FROM owner_question WHERE kind = 'explain_credit'").fetchone()[0] == 1


def test_a_credit_whose_payer_matches_offers_only_that_payers_invoices(web):
    env, _, _ = web
    t, result = _credit(env, 3_000_000, "KAVERI TRADERS")
    assert env.conn.execute("SELECT kind FROM agent_case WHERE id = ?", (result.case_ids[0],)).fetchone()[0] \
        == "ambiguous_match"
    assert json.loads(_question(env, t)["choices_json"])["receivable_ids"] == [KAVERI]


def test_a_matched_credit_raises_no_question(web):
    env, _, _ = web
    _credit(env, 3_300_000, "KAVERI TRADERS")
    assert _status(env, "receivable", KAVERI) == "CONFIRMED"
    assert env.conn.execute("SELECT COUNT(*) FROM owner_question").fetchone()[0] == 0


# --- linking --------------------------------------------------------------------------


def test_the_owner_links_a_credit_and_the_plan_stops_counting_it_twice(web):
    env, client, csrf = web
    t, result = _credit(env, 3_300_000, "K TRADERS", "NEFT9")  # no name match: unknown_txn
    plan_now(env, "t")
    twice = current_run(env)["lowest_balance_paise"]  # the credit in the balance and Kaveri still expected
    mark = last_event_id(env)
    assert _answer(client, csrf, env, _question(env, t), KAVERI).status_code == 303
    assert _status(env, "bank_txn", t) == "MATCHED"
    assert tuple(_rx(env, KAVERI))[:3] == ("CONFIRMED", t, 3_300_000)
    assert env.conn.execute("SELECT party_id FROM bank_txn WHERE id = ?", (t,)).fetchone()[0] == 4
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    assert _status(env, "owner_question", _question(env, t)["id"]) == "ANSWERED"
    assert owner_events(env, mark) == [("BANK_TXN_MATCHED", "owner:1"), ("RECEIVABLE_CONFIRMED", "owner:1"),
                                       ("AGENT_CASE_CLOSED_BY_OWNER", "owner:1")]
    assert twice - current_run(env)["lowest_balance_paise"] == 3_300_000  # counted once now


def test_a_short_payment_is_stated_exactly_and_the_invoice_amount_is_kept(web):
    env, client, csrf = web
    t, _ = _credit(env, 3_000_000, "KAVERI TRADERS")
    assert _answer(client, csrf, env, _question(env, t), KAVERI).status_code == 303
    assert tuple(_rx(env, KAVERI))[:3] == ("CONFIRMED", t, 3_300_000)  # amount_paise never edited
    assert _reasons(env, "RECEIVABLE_CONFIRMED") == [
        "Owner: this ₹30,000 credit settles Kaveri Traders KAVERI-001, short by ₹3,000 (₹33,000 invoiced)."]


def test_an_over_payment_is_stated_exactly_too(web):
    env, client, csrf = web
    t, _ = _credit(env, 3_500_000, "KAVERI TRADERS")
    assert _answer(client, csrf, env, _question(env, t), KAVERI).status_code == 303
    assert tuple(_rx(env, KAVERI))[:3] == ("CONFIRMED", t, 3_300_000)
    assert _reasons(env, "BANK_TXN_MATCHED") == [
        "Owner: this ₹35,000 credit settles Kaveri Traders KAVERI-001, over by ₹2,000 (₹33,000 invoiced)."]


def test_a_part_payment_settles_the_chosen_invoice_and_leaves_the_other_open(web):
    env, client, csrf = web
    t, _ = _credit(env, 15_000_000, "NANDI F")
    assert _answer(client, csrf, env, _question(env, t), NANDI).status_code == 303
    assert tuple(_rx(env, NANDI))[:3] == ("CONFIRMED", t, 20_000_000)
    assert "short by ₹50,000" in _reasons(env, "RECEIVABLE_CONFIRMED")[0]
    assert _status(env, "receivable", KAVERI) == "COMMITTED"


def test_not_an_invoice_closes_the_case_and_leaves_the_credit_unmatched(web):
    env, client, csrf = web
    t, result = _credit(env, 500_000, "INTEREST CREDIT")
    r = post(client, f"/questions/{_question(env, t)['id']}/answer", csrf, {"decision": "not_an_invoice"})
    assert r.status_code == 303
    assert _status(env, "bank_txn", t) == "UNMATCHED"
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    q = _question(env, t)
    assert q["status"] == "ANSWERED" and json.loads(q["answer_json"]) == {"decision": "not_an_invoice"}
    assert _status(env, "receivable", KAVERI) == "COMMITTED" and _status(env, "receivable", NANDI) == "EXPECTED"


def test_the_alias_is_added_only_when_ticked_and_the_next_credit_then_matches(web):
    env, client, csrf = web
    t, _ = _credit(env, 3_300_000, "K TRADERS")
    assert _answer(client, csrf, env, _question(env, t), KAVERI, alias="1").status_code == 303
    assert ("PARTY_ALIAS_ADDED", "owner:1") in owner_events(env)
    assert "K TRADERS" in json.loads(env.conn.execute("SELECT aliases_json FROM party WHERE id = 4").fetchone()[0])
    t2, _ = _credit(env, 20_000_000, "K TRADERS", day=28)  # Kaveri is settled; a K TRADERS credit now names it
    assert _question(env, t2) is not None and env.conn.execute(
        "SELECT kind FROM agent_case ORDER BY id DESC").fetchone()[0] == "unknown_txn"  # no open Kaveri invoice


# --- refused and settled ---------------------------------------------------------------


def test_a_stale_page_or_an_invoice_already_settled_is_refused(web):
    env, client, csrf = web
    t, _ = _credit(env, 3_000_000, "KAVERI TRADERS")
    q = _question(env, t)
    r = post(client, f"/questions/{q['id']}/answer", csrf,
             {"decision": "invoice", "receivable_id": str(KAVERI), f"version_{KAVERI}": "99"})
    assert r.status_code == 409 and _status(env, "bank_txn", t) == "UNMATCHED"
    _credit(env, 3_300_000, "KAVERI TRADERS")  # Kaveri is paid in full by another credit meanwhile
    r = _answer(client, csrf, env, q, KAVERI)
    assert r.status_code == 409 and _status(env, "bank_txn", t) == "UNMATCHED"


def test_another_business_invoice_is_404_and_writes_nothing(web):
    env, client, csrf = web
    add_second_business(env)
    other = writer.create_receivable(
        ReceivableNew(business_id=2, invoice_number="OTHER-1", amount_paise=3_000_000, expected_date=OCT(13),
                      confidence="COMMITTED"), actor="owner:3", reason="test", source_ref=None, conn=env.conn,
        clock=env.clock).id
    t, _ = _credit(env, 3_000_000, "KAVERI TRADERS")
    mark = last_event_id(env)
    r = post(client, f"/questions/{_question(env, t)['id']}/answer", csrf,
             {"decision": "invoice", "receivable_id": str(other), f"version_{other}": "1"})
    assert r.status_code == 404 and owner_events(env, mark) == []


def test_an_invoice_the_question_did_not_offer_is_refused(web):
    env, client, csrf = web
    t, _ = _credit(env, 3_000_000, "KAVERI TRADERS")  # named: only Kaveri's invoice is offered
    assert json.loads(_question(env, t)["choices_json"])["receivable_ids"] == [KAVERI]
    mark = last_event_id(env)
    r = _answer(client, csrf, env, _question(env, t), NANDI)
    assert r.status_code == 409 and owner_events(env, mark) == []
    assert _status(env, "bank_txn", t) == "UNMATCHED" and _status(env, "receivable", NANDI) != "CONFIRMED"


def test_a_credit_settled_meanwhile_closes_its_question_and_links_nothing(web):
    env, client, csrf = web
    t, _ = _credit(env, 3_000_000, "KAVERI TRADERS")
    writer.transition(EntityRef("bank_txn", t), "MATCHED", "reconciler", "matched elsewhere", None,
                      conn=env.conn, clock=env.clock)
    assert _answer(client, csrf, env, _question(env, t), KAVERI).status_code == 303
    assert _status(env, "owner_question", _question(env, t)["id"]) == "ANSWERED"
    assert _status(env, "receivable", KAVERI) == "COMMITTED"


def test_the_helper_cannot_answer(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    try:
        t, _ = _credit(env, 3_000_000, "KAVERI TRADERS")
        csrf = login(client, HELPER)
        r = _answer(client, csrf, env, _question(env, t), KAVERI)
        assert r.status_code == 403 and _status(env, "bank_txn", t) == "UNMATCHED"
    finally:
        env.conn.close()


def test_the_owner_may_confirm_a_receivable_through_the_writer_and_the_ai_may_not(web):
    env, _, _ = web
    t = txn(env, "credit", 3_300_000, OCT(13), "X")
    with pytest.raises(TransitionRefused):
        writer.transition(EntityRef("receivable", KAVERI), "CONFIRMED", "ai", "no", None, conn=env.conn,
                          fields={"matched_txn_id": t}, clock=env.clock)
    writer.transition(EntityRef("receivable", KAVERI), "CONFIRMED", "owner:1", "the owner linked it", None,
                      conn=env.conn, fields={"matched_txn_id": t}, clock=env.clock,
                      expected_version=_rx(env, KAVERI)["version"])
    assert _status(env, "receivable", KAVERI) == "CONFIRMED"


# --- the agent's question and finding -------------------------------------------------


def _agent_question(env, case_id):
    env.conn.execute(
        "INSERT INTO owner_question (business_id, case_id, kind, body_text, choices_json, status) "
        "VALUES (1, ?, 'agent_question', 'What was this credit?', ?, 'OPEN')",
        (case_id, json.dumps({"case_id": case_id})))
    env.conn.execute("UPDATE agent_case SET status = 'ASK_OWNER' WHERE id = ?", (case_id,))  # as to_owner leaves it
    env.conn.commit()


def test_linking_the_credit_also_answers_the_agents_question_on_its_case(web):
    env, client, csrf = web
    t, result = _credit(env, 3_300_000, "K TRADERS")
    _agent_question(env, result.case_ids[0])
    assert _answer(client, csrf, env, _question(env, t), KAVERI).status_code == 303
    assert env.conn.execute("SELECT status FROM owner_question WHERE kind = 'agent_question'").fetchone()[0] \
        == "ANSWERED"


def test_the_credit_can_still_be_linked_after_the_agents_question_closed_its_case(web):
    env, client, csrf = web
    t, result = _credit(env, 3_300_000, "K TRADERS")
    _agent_question(env, result.case_ids[0])
    aq = env.conn.execute("SELECT id FROM owner_question WHERE kind = 'agent_question'").fetchone()[0]
    assert post(client, f"/questions/{aq}/answer", csrf, {"choice": ""}).status_code == 303
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    assert _answer(client, csrf, env, _question(env, t), KAVERI).status_code == 303
    assert _status(env, "receivable", KAVERI) == "CONFIRMED"


def _record_finding(env, case_id, summary, cited):
    state = json.loads(env.conn.execute("SELECT state_json FROM agent_case WHERE id = ?", (case_id,)).fetchone()[0])
    state["findings"] = [{"step": 1, "source": "search_gmail(query='RAVI')", "more": 0, "lines": [
        "message slip-02.eml | 2026-10-13T09:00:00+05:30 | from ravi@ravitraders.example | Weighment slip, "
        "harvest 20 Oct | Advance Rs.2,00,000 paid today by UPI",
        "message other.eml | 2026-10-12T09:00:00+05:30 | from someone@example.test | Unrelated | nothing"]}]
    state["final"] = {"outcome": "NEEDS_OWNER", "summary": summary, "cited_message_ids": cited}
    env.conn.execute("UPDATE agent_case SET state_json = ? WHERE id = ?", (json.dumps(state), case_id))
    env.conn.commit()


def test_needs_attention_shows_the_credit_the_invoices_and_none_preselected(web):
    env, client, _ = web
    t, _ = _credit(env, 15_000_000, "RAVI K (ravi.k@okaxis)", "UPI123")
    page = client.get("/attention").text
    form = page.split("A ₹1,50,000 credit on Tue 13 Oct")[1].split("</article>")[0]
    assert "Kaveri Traders" in form and "Nandi Foods" in form and "₹2,00,000" in form
    assert f'name="receivable_id" value="{KAVERI}"' in form and "checked" not in form
    assert 'value="not_an_invoice"' in form
    assert "The assistant found" not in form  # no finding yet


def test_needs_attention_shows_the_agents_finding_as_its_own_words(web):
    env, client, _ = web
    t, result = _credit(env, 15_000_000, "RAVI K (ravi.k@okaxis)")
    _record_finding(env, result.case_ids[0], "This looks like the harvest advance <b>from Ravi Traders</b>.",
                    ["slip-02.eml"])
    page = client.get("/attention").text
    form = page.split("A ₹1,50,000 credit on Tue 13 Oct")[1].split("</article>")[0]
    assert "The assistant found" in form
    assert "This looks like the harvest advance &lt;b&gt;from Ravi Traders&lt;/b&gt;." in form  # plain text
    assert "ravi@ravitraders.example" in form and "Weighment slip, harvest 20 Oct" in form
    assert "Unrelated" not in form  # only what it cited
    assert "checked" not in form  # the AI informs; the owner decides


def test_the_payer_from_the_alert_is_plain_text(web):
    env, client, _ = web
    _credit(env, 15_000_000, "<script>alert(1)</script>")
    page = client.get("/attention").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
