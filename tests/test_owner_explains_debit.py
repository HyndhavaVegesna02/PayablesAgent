"""The owner says which bill a debit paid (batch 4 plan, CHG-022; clears KL-1).
A debit the reconciler could not match raises an explain_txn question; the
owner answers it on Needs attention through /questions/{id}/answer."""

import json
import re
from datetime import date

import pytest

from app.ledger import writer
from app.ledger.reconcile import match_debit
from app.ledger.writer import EntityRef
from tests.reconcile_helpers import PAPER, txn
from tests.web_helpers import (
    add_second_business,
    current_run,
    last_event_id,
    login,
    make_web_env,
    owner_events,
    plan_now,
    post,
    statuses,
    table_counts,
    version,
)

OCT = lambda d: date(2026, 10, d)  # noqa: E731
ELEC = 3


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _approve(env, bill_id):
    writer.transition(EntityRef("payable", bill_id), "PAYMENT_EXPECTED", "owner:1", "approved", None,
                      conn=env.conn, expected_version=version(env, bill_id), clock=env.clock)


def _owner_paid(env, bill_id):
    writer.transition(EntityRef("payable", bill_id), "PAID", "owner:1", "owner marked paid", None,
                      conn=env.conn, expected_version=version(env, bill_id), clock=env.clock)


def _debit(env, paise, payee, reference=None):
    t = txn(env, "debit", paise, OCT(12), payee, reference)
    with writer.atomic(env.conn):  # as the reconcile_txn job runs it
        result = match_debit(env.conn, t, window_days=3, clock=env.clock)
    return t, result


def _question(env, t):
    return env.conn.execute("SELECT * FROM owner_question WHERE kind = 'explain_txn' "
                            "AND json_extract(choices_json, '$.bank_txn_id') = ?", (t,)).fetchone()


def _answer(client, csrf, env, q, bill_id=None, **extra):
    data = {"decision": "paid", **extra}
    if bill_id is not None:
        data.update({"payable_id": str(bill_id), f"version_{bill_id}": str(version(env, bill_id))})
    return post(client, f"/questions/{q['id']}/answer", csrf, data)


def _status(env, table, row_id):
    return env.conn.execute(f"SELECT status FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]


# --- the question --------------------------------------------------------------------


def test_a_debit_that_does_not_match_raises_one_explain_txn_question(web):
    env, _, _ = web
    t, result = _debit(env, 3_200_000, "UNKNOWN VENDOR", "R77")
    q = _question(env, t)
    assert q["case_id"] == result.case_ids[0]
    assert json.loads(q["choices_json"]) == {"case_id": result.case_ids[0], "bank_txn_id": t}
    assert q["body_text"] == ("A ₹32,000 debit on Mon 12 Oct to UNKNOWN VENDOR (reference R77) was not "
                              "matched to a bill. Which bill did it pay, if any?")
    with writer.atomic(env.conn):  # the job ran twice: still one question
        match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert env.conn.execute("SELECT COUNT(*) FROM owner_question WHERE kind = 'explain_txn'").fetchone()[0] == 1


def test_a_matched_debit_raises_no_question(web):
    env, _, _ = web
    _approve(env, PAPER)
    _debit(env, 18_000_000, "ASHIRWAD PAPER SUPPLIERS")
    assert env.conn.execute("SELECT COUNT(*) FROM owner_question").fetchone()[0] == 0


def test_needs_attention_offers_the_open_bills_closest_amount_first(web):
    env, client, _ = web
    _approve(env, PAPER)
    _approve(env, ELEC)
    t, _ = _debit(env, 17_900_000, "SOMEONE")
    page = client.get("/attention").text
    form = page.split("A ₹1,79,000 debit")[1]
    assert form.index("Ashirwad Paper Suppliers ₹1,80,000") < form.index("City Electricity Board ₹35,000")
    assert "differs by ₹1,000" in form


# --- AC1: KL-1 cleared -----------------------------------------------------------------


def test_kl1_cleared_the_owner_links_a_debit_that_did_not_name_match(web):
    env, client, csrf = web
    _approve(env, PAPER)
    _owner_paid(env, PAPER)
    t, result = _debit(env, 18_000_000, "NEFT DR 0012 ASHIRWAD PAP")  # KL-1: counted twice
    plan_now(env, "t")
    assert current_run(env)["lowest_balance_paise"] == 18_300_000 - 18_000_000
    mark = last_event_id(env)
    assert _answer(client, csrf, env, _question(env, t), PAPER).status_code == 303
    assert _status(env, "bank_txn", t) == "MATCHED"
    paper = env.conn.execute("SELECT status, matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert tuple(paper) == ("PAID", t)
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    assert _status(env, "owner_question", _question(env, t)["id"]) == "ANSWERED"
    assert owner_events(env, mark) == [("BANK_TXN_MATCHED", "owner:1"), ("PAYABLE_PAYMENT_LINKED", "owner:1"),
                                       ("AGENT_CASE_CLOSED_BY_OWNER", "owner:1")]
    assert current_run(env)["lowest_balance_paise"] == 18_300_000  # subtracted once again


def test_linking_an_approved_bill_pays_it_as_the_owner(web):
    env, client, csrf = web
    _approve(env, PAPER)
    t, _ = _debit(env, 18_000_000, "NEFT DR 0012 ASHIRWAD PAP")  # no name match: REVIEW
    assert statuses(env)[PAPER] == "REVIEW"
    assert _answer(client, csrf, env, _question(env, t), PAPER).status_code == 303
    paper = env.conn.execute("SELECT status, matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert tuple(paper) == ("PAID", t)


# --- AC2: an amount difference ------------------------------------------------------------


def test_a_tds_difference_is_linked_and_recorded(web):
    env, client, csrf = web
    _approve(env, PAPER)
    t, result = _debit(env, 16_200_000, "ASHIRWAD PAPER SUPPLIERS")  # 10% TDS deducted
    assert env.conn.execute("SELECT kind FROM agent_case WHERE id = ?", (result.case_ids[0],)).fetchone()[0] == \
        "unknown_txn"
    _answer(client, csrf, env, _question(env, t), PAPER)
    paper = env.conn.execute("SELECT status, amount_paise, matched_txn_id FROM payable WHERE id = ?",
                             (PAPER,)).fetchone()
    assert tuple(paper) == ("PAID", 18_000_000, t)  # the bill keeps its own amount
    reason = env.conn.execute("SELECT reason FROM event WHERE event_type = 'PAYABLE_PAID' "
                              "AND entity_id = ?", (PAPER,)).fetchone()[0]
    assert "debit ₹1,62,000 for a ₹1,80,000 bill: difference ₹18,000" in reason


# --- AC3: the alias ------------------------------------------------------------------------


def test_the_alias_is_added_only_when_ticked_and_the_next_debit_then_matches(web):
    env, client, csrf = web
    _approve(env, PAPER)
    t, _ = _debit(env, 18_000_000, "NEFT DR ASHIRWAD PAP")
    _answer(client, csrf, env, _question(env, t), PAPER, alias="1")
    aliases = json.loads(env.conn.execute("SELECT aliases_json FROM party WHERE id = 1").fetchone()[0])
    assert aliases == ["NEFT DR ASHIRWAD PAP"]
    assert ("PARTY_ALIAS_ADDED", "owner:1") in owner_events(env)
    # A second paper bill: its debit with the same written name now matches by itself.
    from app.domain.models import PayableNew

    bill = writer.create_payable(PayableNew(business_id=1, party_id=1, amount_paise=5_000_000,
                                            due_date=OCT(14), priority="normal"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", bill.id), "CONFIRMED", "owner:1", "t", None, conn=env.conn,
                      expected_version=bill.version, clock=env.clock)
    writer.transition(EntityRef("payable", bill.id), "PLANNED", "planner", "t", None, conn=env.conn,
                      fields={"planned_date": OCT(12)}, clock=env.clock)
    _approve(env, bill.id)
    second, result = _debit(env, 5_000_000, "NEFT DR ASHIRWAD PAP", "R2")
    assert result.outcome == f"matched bill {bill.id}: PAID"


def test_without_the_tick_the_vendor_is_unchanged(web):
    env, client, csrf = web
    _approve(env, PAPER)
    t, _ = _debit(env, 18_000_000, "NEFT DR ASHIRWAD PAP")
    _answer(client, csrf, env, _question(env, t), PAPER)
    assert env.conn.execute("SELECT aliases_json FROM party WHERE id = 1").fetchone()[0] == "[]"


# --- AC4: the other bills held for the debit -----------------------------------------------


def test_the_other_review_bills_go_back_to_expected(web):
    env, client, csrf = web
    from app.domain.models import PayableNew

    _approve(env, PAPER)
    twin = writer.create_payable(PayableNew(business_id=1, party_id=2, amount_paise=18_000_000,
                                            due_date=OCT(13), priority="normal"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "CONFIRMED", "owner:1", "t", None, conn=env.conn,
                      expected_version=twin.version, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "PLANNED", "planner", "t", None, conn=env.conn,
                      fields={"planned_date": OCT(12)}, clock=env.clock)
    _approve(env, twin.id)
    t, result = _debit(env, 18_000_000, "SOMEONE ELSE")
    assert statuses(env)[PAPER] == statuses(env)[twin.id] == "REVIEW"
    _answer(client, csrf, env, _question(env, t), PAPER)
    assert statuses(env)[PAPER] == "PAID" and statuses(env)[twin.id] == "PAYMENT_EXPECTED"
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"


# --- AC5: not a bill payment ---------------------------------------------------------------


def test_not_a_bill_payment_closes_the_case_and_leaves_the_debit_counted(web):
    env, client, csrf = web
    t, result = _debit(env, 3_200_000, "LANDLORD")
    plan_now(env, "t")
    lowest = current_run(env)["lowest_balance_paise"]
    mark = last_event_id(env)
    r = post(client, f"/questions/{_question(env, t)['id']}/answer", csrf, {"decision": "not_a_bill"})
    assert r.status_code == 303
    assert _status(env, "bank_txn", t) == "UNMATCHED"
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    assert owner_events(env, mark) == [("AGENT_CASE_CLOSED_BY_OWNER", "owner:1")]
    assert current_run(env)["lowest_balance_paise"] == lowest


# --- AC6: refusals write nothing -----------------------------------------------------------


def test_another_business_bill_is_404_and_writes_nothing(web):
    env, client, csrf = web
    other = add_second_business(env)
    t, _ = _debit(env, 500_000, "SOMEONE")
    before = table_counts(env)
    r = post(client, f"/questions/{_question(env, t)['id']}/answer", csrf,
             {"decision": "paid", "payable_id": str(other), f"version_{other}": "2"})
    assert r.status_code == 404 and table_counts(env) == before
    assert _status(env, "bank_txn", t) == "UNMATCHED"


def test_a_stale_bill_version_or_a_bill_not_waiting_for_payment_is_refused(web):
    env, client, csrf = web
    _approve(env, PAPER)
    t, _ = _debit(env, 18_000_000, "SOMEONE ELSE")
    q = _question(env, t)
    r = post(client, f"/questions/{q['id']}/answer", csrf,
             {"decision": "paid", "payable_id": str(PAPER), f"version_{PAPER}": "1"})
    assert r.status_code == 409 and _status(env, "bank_txn", t) == "UNMATCHED"
    r = post(client, f"/questions/{q['id']}/answer", csrf,
             {"decision": "paid", "payable_id": "5", "version_5": str(version(env, 5))})  # Prime: not approved
    assert r.status_code == 409 and _status(env, "bank_txn", t) == "UNMATCHED"
    r = post(client, f"/questions/{q['id']}/answer", csrf, {"decision": "paid"})
    assert r.status_code == 422


def test_a_debit_settled_meanwhile_closes_its_question_and_links_nothing(web):
    env, client, csrf = web
    t, result = _debit(env, 3_200_000, "SOMEONE")
    writer.transition(EntityRef("bank_txn", t), "REVERSED", "reconciler", "returned", None, conn=env.conn,
                      clock=env.clock)
    assert "Close this question" in client.get("/attention").text
    r = post(client, f"/questions/{_question(env, t)['id']}/answer", csrf, {"decision": "settled"})
    assert r.status_code == 303
    assert _status(env, "owner_question", _question(env, t)["id"]) == "ANSWERED"
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    assert _status(env, "bank_txn", t) == "REVERSED"


def test_the_payee_from_the_alert_is_plain_text(web):
    env, client, _ = web
    _debit(env, 3_200_000, '<script>alert(1)</script>" onclick="x')
    page = client.get("/attention").text
    assert "<script>alert(1)" not in page and 'onclick="x' not in page
    assert re.search(r"&lt;script&gt;alert\(1\)&lt;/script&gt;&#34; onclick=&#34;x", page)


# --- batch 4 review round 1 ---------------------------------------------------------------


def _twin_in_review(env):
    from app.domain.models import PayableNew

    _approve(env, PAPER)
    twin = writer.create_payable(PayableNew(business_id=1, party_id=2, amount_paise=18_000_000,
                                            due_date=OCT(13), priority="normal"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "CONFIRMED", "owner:1", "t", None, conn=env.conn,
                      expected_version=twin.version, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "PLANNED", "planner", "t", None, conn=env.conn,
                      fields={"planned_date": OCT(12)}, clock=env.clock)
    _approve(env, twin.id)
    t, result = _debit(env, 18_000_000, "SOMEONE ELSE")
    assert statuses(env)[PAPER] == statuses(env)[twin.id] == "REVIEW"
    return twin.id, t, result


def test_one_debit_never_pays_two_bills(web):
    # Review C1 (both halves): mark Paper paid with the held debit, then answer the
    # question with the twin. The debit already pays Paper: the question is settled,
    # the twin goes back to expected, and nothing is linked twice.
    env, client, csrf = web
    twin, t, result = _twin_in_review(env)
    plan_now(env, "t")
    assert post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))}).status_code == 303
    assert env.conn.execute("SELECT matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()[0] == t
    assert statuses(env)[twin] == "PAYMENT_EXPECTED"
    assert _status(env, "owner_question", _question(env, t)["id"]) == "ANSWERED"  # settled by the mark-paid
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    r = _answer(client, csrf, env, _question(env, t), twin)
    assert r.status_code == 409  # already answered: the debit can't be given to the twin too
    held = env.conn.execute("SELECT COUNT(*) FROM payable WHERE matched_txn_id = ?", (t,)).fetchone()[0]
    assert held == 1 and statuses(env)[twin] == "PAYMENT_EXPECTED"


def test_the_writer_refuses_to_link_a_held_debit_to_a_second_bill(web):
    env, _, _ = web
    twin, t, _ = _twin_in_review(env)
    writer.transition(EntityRef("payable", PAPER), "PAID", "owner:1", "x", None, conn=env.conn,
                      expected_version=version(env, PAPER), fields={"matched_txn_id": t}, clock=env.clock)
    from app.domain.states import IllegalTransition

    with pytest.raises(IllegalTransition, match="already pays bill"):
        writer.transition(EntityRef("payable", twin), "PAID", "owner:1", "x", None, conn=env.conn,
                          expected_version=version(env, twin), fields={"matched_txn_id": t}, clock=env.clock)


def test_not_a_bill_payment_returns_the_held_bills_to_expected(web):
    env, client, csrf = web
    twin, t, _ = _twin_in_review(env)
    r = post(client, f"/questions/{_question(env, t)['id']}/answer", csrf, {"decision": "not_a_bill"})
    assert r.status_code == 303
    assert statuses(env)[PAPER] == statuses(env)[twin] == "PAYMENT_EXPECTED"
    assert _status(env, "bank_txn", t) == "UNMATCHED"
    from app.db.read import build_snapshot

    ids = {p.payable_id for p in build_snapshot(env.conn, 1, env.clock.today()).payables}
    assert {PAPER, twin} <= ids  # their outflows are counted again


def test_no_bill_is_preselected_for_a_link(web):
    env, client, _ = web
    _approve(env, PAPER)
    _debit(env, 18_000_000, "SOMEONE ELSE")
    form = client.get("/attention").text.split("This debit paid")[1].split("</form>")[0]
    assert "checked" not in form


# --- CHG-027: a case has two questions, the explain_txn and the agent's ------------------------


def _agent_asked(env, case_id):
    """The agent ran out of ideas on the case and asked the owner (as run_case does)."""
    env.conn.execute("UPDATE agent_case SET status = 'ASK_OWNER' WHERE id = ?", (case_id,))
    cur = env.conn.execute(
        "INSERT INTO owner_question (business_id, case_id, kind, body_text, choices_json, status) "
        "VALUES (1, ?, 'agent_question', 'What was this debit?', ?, 'OPEN')",
        (case_id, json.dumps({"case_id": case_id, "choices": []})))
    env.conn.commit()
    return cur.lastrowid


def test_explaining_the_debit_also_answers_the_agents_question_on_its_case(web):
    env, client, csrf = web
    t, result = _debit(env, 3_200_000, "LANDLORD")
    agent_q = _agent_asked(env, result.case_ids[0])
    r = post(client, f"/questions/{_question(env, t)['id']}/answer", csrf, {"decision": "not_a_bill"})
    assert r.status_code == 303
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    assert _status(env, "owner_question", agent_q) == "ANSWERED"  # it no longer waits on Needs attention
    assert "What was this debit?" not in client.get("/attention").text


def test_the_debit_can_still_be_explained_after_the_agents_question_closed_its_case(web):
    env, client, csrf = web
    _approve(env, PAPER)
    _owner_paid(env, PAPER)
    t, result = _debit(env, 18_000_000, "NEFT DR 0012 ASHIRWAD PAP")
    agent_q = _agent_asked(env, result.case_ids[0])
    assert post(client, f"/questions/{agent_q}/answer", csrf, {"choice": ""}).status_code == 303
    assert _status(env, "agent_case", result.case_ids[0]) == "CLOSED_BY_OWNER"
    assert _answer(client, csrf, env, _question(env, t), PAPER).status_code == 303  # was refused (409): the case was closed
    assert _status(env, "bank_txn", t) == "MATCHED"
    assert _status(env, "owner_question", _question(env, t)["id"]) == "ANSWERED"
