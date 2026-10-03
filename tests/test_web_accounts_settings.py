"""Accounts, confirm-balance, settings, priorities, and the routes whose
backend lands later (batch 3 plan, CHG-006 S5; AC5, AC6)."""

import json

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
    table_counts,
    version,
)

PRIME = 5
SETTINGS = {"safety_amount": "2,50,000", "escalation_amount": "50,000", "horizon_days": "14",
            "payment_days": ["MON", "THU"], "language": "en"}


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _ask_owner(env, reported=41_200_000):
    """The drift check could not explain a gap: the account waits for the owner."""
    writer.record_reported_balance(1, reported, "2026-10-12T08:30:00+05:30", "reconciler", "report", None,
                                   conn=env.conn, reconciled=False, clock=env.clock)
    writer.set_drift_status(1, "CHECKING", "reconciler", "gap", None, conn=env.conn, clock=env.clock)
    writer.set_drift_status(1, "ASK_OWNER", "reconciler", "still a gap", None, conn=env.conn, clock=env.clock)


def test_accounts_shows_balances_drift_and_gmail_not_connected(web):
    _, client, _ = web
    page = client.get("/accounts").text
    assert "HDFC Bank" in page and "XXXX4821" in page
    assert "₹6,20,000" in page and "Matches" in page
    assert "Not connected (set up later)" in page
    assert "/gmail/" not in page


def test_confirm_balance_on_an_account_waiting_for_the_owner_writes_an_adjustment(web):
    env, client, csrf = web
    _ask_owner(env)
    qid = env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, status) VALUES "
                           "(1, 'confirm_balance', 'HDFC shows ₹4,12,000; I calculate ₹6,20,000.', 'OPEN')").lastrowid
    env.conn.commit()
    assert "Needs your confirmation" in client.get("/accounts").text
    mark = last_event_id(env)
    r = post(client, "/accounts/1/confirm-balance", csrf, {"amount": "4,12,000"})
    assert r.status_code == 303
    adj = env.conn.execute("SELECT direction, amount_paise, status FROM bank_txn").fetchone()
    assert tuple(adj) == ("debit", 20_800_000, "ADJUSTMENT")
    assert env.conn.execute("SELECT drift_status FROM bank_account").fetchone()[0] == "OK"
    assert ("BANK_ACCOUNT_OK", "owner:1") in owner_events(env, mark)
    assert env.conn.execute("SELECT status FROM owner_question WHERE id = ?", (qid,)).fetchone()[0] == "ANSWERED"
    assert current_run(env)["opening_cash_paise"] == 41_200_000


def test_confirm_balance_through_its_question(web):
    env, client, csrf = web
    _ask_owner(env)
    qid = env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, choices_json, status) VALUES "
                           "(1, 'confirm_balance', 'What is the actual balance?', ?, 'OPEN')",
                           (json.dumps({"account_id": 1}),)).lastrowid
    env.conn.commit()
    assert post(client, f"/questions/{qid}/answer", csrf, {"amount": "₹4,12,000"}).status_code == 303
    assert env.conn.execute("SELECT drift_status FROM bank_account").fetchone()[0] == "OK"


def test_confirm_balance_is_refused_when_the_account_is_not_waiting(web):
    env, client, csrf = web
    r = post(client, "/accounts/1/confirm-balance", csrf, {"amount": "6,20,000"})
    assert r.status_code == 409 and "not waiting for you to confirm" in r.text
    assert env.conn.execute("SELECT COUNT(*) FROM bank_txn").fetchone()[0] == 0


def test_an_unreadable_balance_is_a_field_error(web):
    env, client, csrf = web
    _ask_owner(env)
    r = post(client, "/accounts/1/confirm-balance", csrf, {"amount": "about four lakh"})
    assert r.status_code == 422 and "Enter the balance in rupees" in r.text
    assert env.conn.execute("SELECT drift_status FROM bank_account").fetchone()[0] == "ASK_OWNER"


def test_a_settings_change_is_an_event_and_replans(web):
    env, client, csrf = web
    mark = last_event_id(env)
    r = post(client, "/settings", csrf, {**SETTINGS, "safety_amount": "1,50,000"})
    assert r.status_code == 303
    assert owner_events(env, mark)[0] == ("BUSINESS_SETTINGS_CHANGED", "owner:1")
    ev = env.conn.execute("SELECT before_json, after_json FROM event WHERE event_type = 'BUSINESS_SETTINGS_CHANGED'"
                          ).fetchone()
    assert json.loads(ev[0])["safety_amount_paise"] == 25_000_000
    assert json.loads(ev[1])["safety_amount_paise"] == 15_000_000
    run = current_run(env)
    assert run["triggered_by"] == f"event:{mark + 1}" and run["valid"] == 1
    assert plan_lines(env)[PRIME] == ("PAY", "2026-10-22")  # ₹1,83,000 now clears ₹1,50,000


def test_payment_days_and_horizon_change_the_plan(web):
    env, client, csrf = web
    post(client, "/settings", csrf, {**SETTINGS, "payment_days": ["TUE", "FRI"], "horizon_days": "7"})
    b = env.conn.execute("SELECT payment_days, horizon_days FROM business").fetchone()
    assert tuple(b) == ("TUE,FRI", 7)
    days = env.conn.execute("SELECT COUNT(*) FROM plan_day WHERE plan_run_id = ?", (current_run(env)["id"],)).fetchone()
    assert days[0] == 7


def test_saving_unchanged_settings_records_nothing(web):
    env, client, csrf = web
    before = table_counts(env)
    assert post(client, "/settings", csrf, SETTINGS).status_code == 303
    assert table_counts(env) == before


@pytest.mark.parametrize("change, field", [
    ({"safety_amount": "lots"}, "safety_amount"), ({"horizon_days": "0"}, "horizon_days"),
    ({"horizon_days": "two weeks"}, "horizon_days"), ({"payment_days": []}, "payment_days"),
    ({"payment_days": ["MON", "XYZ"]}, "payment_days"), ({"language": "hi"}, "language"),
])
def test_unreadable_settings_change_nothing(web, change, field):
    env, client, csrf = web
    before = table_counts(env)
    data = {**SETTINGS, **change}
    if data["payment_days"] == []:
        del data["payment_days"]
    r = post(client, "/settings", csrf, data)
    assert r.status_code == 422 and f'id="err-{field}"' in r.text
    assert table_counts(env) == before


def test_a_priority_change_is_an_event_and_replans(web):
    env, client, csrf = web
    mark = last_event_id(env)
    r = post(client, "/settings", csrf, {"payable_id": str(PRIME), "priority": "critical",
                                         "version": str(version(env, PRIME))})
    assert r.status_code == 303
    assert owner_events(env, mark) == [("PAYABLE_PRIORITY_CHANGED", "owner:1")]
    assert env.conn.execute("SELECT priority FROM payable WHERE id = ?", (PRIME,)).fetchone()[0] == "critical"
    assert current_run(env)["triggered_by"] == f"event:{mark + 1}"


def test_a_priority_change_with_an_old_version_is_refused(web):
    env, client, csrf = web
    r = post(client, "/settings", csrf, {"payable_id": str(PRIME), "priority": "critical", "version": "1"})
    assert r.status_code == 409
    assert env.conn.execute("SELECT priority FROM payable WHERE id = ?", (PRIME,)).fetchone()[0] == "normal"


def test_a_paid_bills_priority_is_fixed(web):
    env, _, _ = web
    from app.domain.states import IllegalTransition
    from app.ledger.writer import EntityRef

    env.conn.execute("UPDATE payable SET status = 'PAID' WHERE id = ?", (PRIME,))
    env.conn.commit()
    with pytest.raises(IllegalTransition, match="priority is fixed"):
        writer.set_priority(EntityRef("payable", PRIME), "critical", "owner:1", "x", None, conn=env.conn,
                            expected_version=version(env, PRIME), clock=env.clock)


def test_writer_settings_refuse_a_helper_and_unknown_fields(web):
    env, _, _ = web
    from app.domain.states import FieldNotAllowed, InvalidActor

    with pytest.raises(FieldNotAllowed):
        writer.update_business_settings(1, {"name": "x"}, "owner:1", "x", None, conn=env.conn, clock=env.clock)
    with pytest.raises(InvalidActor):
        writer.update_business_settings(1, {"horizon_days": 7}, "helper:2", "x", None, conn=env.conn,
                                        clock=env.clock)


def test_unlock_on_a_document_that_is_not_locked_says_so(web):
    env, client, csrf = web
    doc = env.conn.execute("INSERT INTO source_document (business_id, kind, content_sha256, received_at) "
                           "VALUES (1, 'pdf', 'open-sha', '2026-10-12T09:00:00+05:30')").lastrowid
    env.conn.commit()
    r = post(client, f"/documents/{doc}/unlock", csrf, {"password": "x"})
    assert r.status_code == 409 and "nothing to unlock" in r.text
    assert post(client, "/documents/999/unlock", csrf).status_code == 404


def test_bank_change_is_refused_with_no_pending_change(web):
    _, client, csrf = web
    r = post(client, "/parties/3/bank-change", csrf, {"decision": "approve"})
    assert r.status_code == 409 and "no pending bank change" in r.text
    assert post(client, "/parties/999/bank-change", csrf).status_code == 404
