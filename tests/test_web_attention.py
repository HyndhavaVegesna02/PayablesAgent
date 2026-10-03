"""Needs attention: confirming and rejecting entries, choosing a shortfall
option, answering questions (batch 3 plan, CHG-006 S3 to S5; AC1, AC5, AC6)."""

import json
import re

import pytest

from app.ledger import writer
from tests.web_helpers import (
    current_run,
    last_event_id,
    login,
    make_web_env,
    owner_events,
    plan_lines,
    plan_now,
    post,
    statuses,
    table_counts,
)

PRIME = 5
BILL = {"kind": "bill", "party": "Sharma Packaging", "invoice_number": "SP-7", "amount": "Rs.12,000",
        "due_date": "2026-10-24", "priority": "normal"}


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _candidate_ids(client):
    return [int(i) for i in dict.fromkeys(re.findall(r"/candidates/(\d+)/confirm", client.get("/attention").text))]


def _options(client):
    page = client.get("/attention").text
    return dict(zip(re.findall(r"<p><strong>(.*?)</strong></p>", page),
                    [int(i) for i in dict.fromkeys(re.findall(r"/options/(\d+)/choose", page))]))


# --- typed entries ------------------------------------------------------------------


def test_a_confirmed_typed_bill_becomes_confirmed_and_is_planned(web):
    env, client, csrf = web
    assert post(client, "/entries", csrf, BILL).status_code == 303
    (cid,) = _candidate_ids(client)
    mark = last_event_id(env)
    r = post(client, f"/candidates/{cid}/confirm", csrf, {**BILL, "amount": "₹12,000"})
    assert r.status_code == 303
    bill = env.conn.execute("SELECT * FROM payable WHERE invoice_number = 'SP-7'").fetchone()
    assert (bill["amount_paise"], bill["status"], bill["planned_date"]) == (1_200_000, "PLANNED", "2026-10-22")
    party = env.conn.execute("SELECT kind, name FROM party WHERE id = ?", (bill["party_id"],)).fetchone()
    assert tuple(party) == ("vendor", "Sharma Packaging")
    assert owner_events(env, mark) == [("PAYABLE_CREATED", "owner:1"), ("PAYABLE_CONFIRMED", "owner:1"),
                                       ("CANDIDATE_ACCEPTED", "owner:1")]
    assert plan_lines(env)[bill["id"]] == ("PAY", "2026-10-22")
    assert env.conn.execute("SELECT status FROM candidate WHERE id = ?", (cid,)).fetchone()[0] == "ACCEPTED"
    assert _candidate_ids(client) == []


def test_the_owners_edits_are_what_gets_recorded(web):
    env, client, csrf = web
    post(client, "/entries", csrf, BILL)
    (cid,) = _candidate_ids(client)
    post(client, f"/candidates/{cid}/confirm", csrf, {**BILL, "amount": "15,000", "priority": "flexible"})
    bill = env.conn.execute("SELECT amount_paise, priority FROM payable WHERE invoice_number = 'SP-7'").fetchone()
    assert tuple(bill) == (1_500_000, "flexible")


@pytest.mark.parametrize("change, field", [({"amount": "twelve thousand"}, "amount"),
                                           ({"due_date": ""}, "due_date"), ({"party": " "}, "party")])
def test_an_unreadable_edit_is_a_field_error_and_nothing_is_recorded(web, change, field):
    env, client, csrf = web
    post(client, "/entries", csrf, BILL)
    (cid,) = _candidate_ids(client)
    before = table_counts(env)
    r = post(client, f"/candidates/{cid}/confirm", csrf, {**BILL, **change})
    assert r.status_code == 422 and f'id="err-{field}"' in r.text
    assert table_counts(env) == before


def test_confirming_runs_the_rule_checks_again(web):
    env, client, csrf = web
    post(client, "/entries", csrf, BILL)
    (cid,) = _candidate_ids(client)
    r = post(client, f"/candidates/{cid}/confirm", csrf, {**BILL, "invoice_date": "2026-10-30"})
    assert r.status_code == 422 and "is before the invoice date" in r.text
    assert env.conn.execute("SELECT COUNT(*) FROM payable WHERE invoice_number = 'SP-7'").fetchone()[0] == 0


def test_a_typed_sales_invoice_becomes_a_receivable(web):
    env, client, csrf = web
    invoice = {"kind": "invoice", "party": "Kaveri Traders", "invoice_number": "INV-9", "amount": "50,000",
               "expected_date": "2026-10-20", "confidence": "COMMITTED"}
    post(client, "/entries", csrf, invoice)
    (cid,) = _candidate_ids(client)
    assert post(client, f"/candidates/{cid}/confirm", csrf, invoice).status_code == 303
    rec = env.conn.execute("SELECT * FROM receivable WHERE invoice_number = 'INV-9'").fetchone()
    assert (rec["amount_paise"], rec["confidence"], rec["party_id"]) == (5_000_000, "COMMITTED", 4)  # the existing customer
    assert current_run(env)["lowest_balance_paise"] == 18_300_000 + 5_000_000


def test_a_rejected_entry_is_recorded_and_creates_nothing(web):
    env, client, csrf = web
    post(client, "/entries", csrf, BILL)
    (cid,) = _candidate_ids(client)
    mark = last_event_id(env)
    assert post(client, f"/candidates/{cid}/reject", csrf).status_code == 303
    assert env.conn.execute("SELECT status FROM candidate WHERE id = ?", (cid,)).fetchone()[0] == "REJECTED"
    assert owner_events(env, mark) == [("CANDIDATE_REJECTED", "owner:1")]
    assert env.conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 5
    assert post(client, f"/candidates/{cid}/confirm", csrf, BILL).status_code == 409


def test_an_unknown_entry_is_404(web):
    _, client, csrf = web
    assert post(client, "/candidates/999/confirm", csrf, BILL).status_code == 404


# --- a bank email the checks could not settle ----------------------------------------


def _awaiting_alert(env):
    doc = env.conn.execute(
        "INSERT INTO source_document (business_id, kind, external_ref, content_sha256, received_at, status, doc_type) "
        "VALUES (1, 'email', '<m1@x>', 'sha-m1', '2026-10-12T08:00:00+05:30', 'PROCESSED', 'bank_alert')"
    ).lastrowid
    payload = {"doc_type": "bank_alert", "record": None, "dedup_key": None,
               "extract": {"account_last4": "4821", "direction": "debit", "amount_text": "Rs.32,000",
                           "txn_date": "2026-10-12", "counterparty": "UNKNOWN VENDOR", "reference": "R77",
                           "available_balance_text": None, "uncertain_fields": ["amount_text"]}}
    cid = env.conn.execute(
        "INSERT INTO candidate (source_document_id, record_type, payload_json, checks_json, status, attempts, "
        "created_by, created_at) VALUES (?, 'txn', ?, ?, 'AWAITING_OWNER', 3, 'pipeline', '2026-10-12T09:00:00+05:30')",
        (doc, json.dumps(payload), json.dumps({"confidence": "failed: the model was unsure of amount_text"})),
    ).lastrowid
    qid = env.conn.execute(
        "INSERT INTO owner_question (business_id, kind, body_text, choices_json, status) "
        "VALUES (1, 'confirm_record', 'Please check this bank email.', ?, 'OPEN')",
        (json.dumps({"candidate_id": cid}),),
    ).lastrowid
    env.conn.commit()
    return cid, qid


def test_confirming_an_alert_creates_an_unmatched_txn_as_the_owner_and_queues_matching(web):
    env, client, csrf = web
    cid, qid = _awaiting_alert(env)
    page = client.get("/attention").text
    assert 'value="Rs.32,000"' in page and "the model was unsure of amount_text" in page
    form = {"account_id": "1", "direction": "debit", "amount": "Rs.32,000", "txn_date": "2026-10-12",
            "counterparty": "UNKNOWN VENDOR", "reference": "R77"}
    r = post(client, f"/questions/{qid}/answer", csrf, form)
    assert r.status_code == 303
    t = env.conn.execute("SELECT * FROM bank_txn WHERE candidate_id = ?", (cid,)).fetchone()
    assert (t["status"], t["amount_paise"], t["dedup_key"]) == ("UNMATCHED", 3_200_000, "1:2026-10-12:debit:3200000:R77")
    ev = env.conn.execute("SELECT actor FROM event WHERE entity = 'bank_txn' AND entity_id = ?", (t["id"],)).fetchone()
    assert ev[0] == "owner:1"
    job = env.conn.execute("SELECT kind, payload_json FROM job WHERE kind = 'reconcile_txn'").fetchone()
    assert json.loads(job["payload_json"]) == {"bank_txn_id": t["id"]}
    assert env.conn.execute("SELECT status FROM owner_question WHERE id = ?", (qid,)).fetchone()[0] == "ANSWERED"
    assert env.conn.execute("SELECT status FROM candidate WHERE id = ?", (cid,)).fetchone()[0] == "ACCEPTED"
    assert current_run(env)["opening_cash_paise"] == 62_000_000 - 3_200_000


def test_an_alert_dated_in_the_future_is_a_field_error(web):
    env, client, csrf = web
    cid, _ = _awaiting_alert(env)
    form = {"account_id": "1", "direction": "debit", "amount": "32,000", "txn_date": "2026-10-13"}
    r = post(client, f"/candidates/{cid}/confirm", csrf, form)
    assert r.status_code == 422 and "can&#39;t be in the future" in r.text
    assert env.conn.execute("SELECT COUNT(*) FROM bank_txn").fetchone()[0] == 0


def test_rejecting_through_the_question_closes_it(web):
    env, client, csrf = web
    cid, qid = _awaiting_alert(env)
    assert post(client, f"/questions/{qid}/answer", csrf, {"decision": "reject"}).status_code == 303
    assert env.conn.execute("SELECT status FROM candidate WHERE id = ?", (cid,)).fetchone()[0] == "REJECTED"
    assert env.conn.execute("SELECT status FROM owner_question WHERE id = ?", (qid,)).fetchone()[0] == "ANSWERED"


def test_a_question_without_its_entry_link_is_refused(web):
    env, client, csrf = web
    qid = env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, status) "
                           "VALUES (1, 'confirm_record', 'x', 'OPEN')").lastrowid
    env.conn.commit()
    assert post(client, f"/questions/{qid}/answer", csrf).status_code == 409


def test_an_agent_question_waits_for_the_agent(web):
    env, client, csrf = web
    qid = env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, status) "
                           "VALUES (1, 'reconnect_gmail', 'Gmail needs reconnecting.', 'OPEN')").lastrowid
    env.conn.commit()
    r = post(client, f"/questions/{qid}/answer", csrf, {"answer": "rent"})
    assert r.status_code == 409 and "later change" in r.text


# --- shortfall options --------------------------------------------------------------


def test_the_worked_example_options_are_offered(web):
    _, client, _ = web
    assert list(_options(client)) == [
        "Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct",
        "Split Prime Chem Industries: ₹53,000 now, ₹67,000 due Mon 26 Oct",
        "Authorise going below the safety amount (₹67,000 below on Thu 22 Oct)",
    ]


def test_choosing_early_receipt_records_the_choice_and_changes_no_ledger_row(web):
    env, client, csrf = web
    option_id = _options(client)["Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct"]
    ledger = [env.conn.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in ("payable", "receivable", "bank_txn")]
    mark = last_event_id(env)
    assert post(client, f"/options/{option_id}/choose", csrf).status_code == 303
    row = env.conn.execute("SELECT chosen_by, chosen_at FROM shortfall_option WHERE id = ?", (option_id,)).fetchone()
    assert tuple(row) == (1, env.clock.now().isoformat())
    assert owner_events(env, mark) == [("SHORTFALL_OPTION_CHOSEN", "owner:1")]
    after = [env.conn.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in ("payable", "receivable", "bank_txn")]
    assert [list(map(tuple, x)) for x in after] == [list(map(tuple, x)) for x in ledger]
    assert current_run(env)["triggered_by"] == f"event:{mark + 1}"


def test_choosing_the_split_splits_prime_chem_and_pays_53000_on_thursday(web):
    env, client, csrf = web
    option_id = _options(client)["Split Prime Chem Industries: ₹53,000 now, ₹67,000 due Mon 26 Oct"]
    assert post(client, f"/options/{option_id}/choose", csrf).status_code == 303
    assert statuses(env)[PRIME] == "SPLIT"
    children = env.conn.execute("SELECT id, amount_paise, due_date FROM payable WHERE parent_payable_id = ? "
                                "ORDER BY id", (PRIME,)).fetchall()
    assert [tuple(c)[1:] for c in children] == [(5_300_000, "2026-10-22"), (6_700_000, "2026-10-26")]
    lines = plan_lines(env)
    assert lines[children[0]["id"]] == ("PAY", "2026-10-22")
    run = current_run(env)
    assert (run["lowest_balance_paise"], run["valid"]) == (25_000_000, 1)


def test_choosing_authorise_breach_is_recorded_and_honoured(web):
    # Recorded only in batch 3; since batch 4 (CHG-021) the planner pays the bill.
    env, client, csrf = web
    option_id = _options(client)["Authorise going below the safety amount (₹67,000 below on Thu 22 Oct)"]
    assert post(client, f"/options/{option_id}/choose", csrf).status_code == 303
    assert env.conn.execute("SELECT chosen_by FROM shortfall_option WHERE id = ?", (option_id,)).fetchone()[0] == 1
    assert statuses(env)[PRIME] == "PLANNED"


def test_choosing_ask_ca_adds_a_ca_reminder(web):
    env, client, csrf = web
    run = current_run(env)
    option_id = env.conn.execute("INSERT INTO shortfall_option (plan_run_id, kind, params_json, meets_rule) "
                                 "VALUES (?, 'ask_ca', '{}', 0)", (run["id"],)).lastrowid
    env.conn.commit()
    assert post(client, f"/options/{option_id}/choose", csrf).status_code == 303
    q = env.conn.execute("SELECT kind, status FROM owner_question").fetchone()
    assert tuple(q) == ("ca_reminder", "OPEN")


def test_an_option_from_an_old_plan_is_refused(web):
    env, client, csrf = web
    option_id = _options(client)["Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct"]
    plan_now(env, "event:later")
    r = post(client, f"/options/{option_id}/choose", csrf)
    assert r.status_code == 409 and "The plan changed since you opened it" in r.text
    assert env.conn.execute("SELECT chosen_by FROM shortfall_option WHERE id = ?", (option_id,)).fetchone()[0] is None


def test_an_option_with_malformed_params_is_refused_and_writes_nothing(web):
    env, client, csrf = web
    run = current_run(env)
    option_id = env.conn.execute("INSERT INTO shortfall_option (plan_run_id, kind, params_json, meets_rule) "
                                 "VALUES (?, 'split', '{\"payable_id\": \"five\"}', 1)", (run["id"],)).lastrowid
    env.conn.commit()
    before = table_counts(env)
    r = post(client, f"/options/{option_id}/choose", csrf)
    assert r.status_code == 409 and "can&#39;t be applied" in r.text
    assert table_counts(env) == before


def test_writer_refuses_a_second_choice_of_the_same_option(web):
    env, _, _ = web
    option_id = env.conn.execute("SELECT id FROM shortfall_option WHERE kind = 'early_receipt'").fetchone()[0]
    writer.choose_option(option_id, "owner:1", "x", None, conn=env.conn, clock=env.clock)
    from app.domain.states import IllegalTransition

    with pytest.raises(IllegalTransition):
        writer.choose_option(option_id, "owner:1", "x", None, conn=env.conn, clock=env.clock)
