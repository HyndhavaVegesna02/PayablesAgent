"""Drift (batch 2 plan, CHG-005 AC5-AC7; TDD Part 2, "Drift check"): the writer
owns every bank_account change, an alert's mismatch waits for the 23:00
recheck, a statement's is acted on at once, a found transaction closes the
gap, and the owner's confirm_balance writes the adjustment."""

from datetime import date, datetime, timedelta

import pytest

from app.clock import TIMEZONE
from app.domain.states import ActorNotAllowed, AgentActorRefused, IllegalTransition
from app.jobs import queue
from app.jobs.reconcile import handle_drift_check, handle_reconcile_txn
from app.jobs.replan import replan
from app.ledger import writer
from app.ledger.reconcile import check_drift
from app.worker import process_one
from tests.reconcile_helpers import cases, txn
from tests.worker_helpers import make_env

ALERT_AT = datetime(2026, 10, 15, 12, 30, 41, tzinfo=TIMEZONE)


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    e.clock.advance(timedelta(days=3, hours=4))  # Thu 15 Oct, 13:00
    yield e
    e.conn.close()


def account(env):
    return env.conn.execute("SELECT * FROM bank_account WHERE id = 1").fetchone()


def drift_events(env):
    return [tuple(r) for r in env.conn.execute(
        "SELECT event_type, actor FROM event WHERE entity = 'bank_account' ORDER BY id")]


def _missed_debit_alert(env):
    """Electricity's ₹35,000 debit; the alert says ₹5,65,000 is left, but the
    ledger (₹6,20,000 opening) makes it ₹5,85,000: a ₹20,000 debit sent no alert."""
    txn(env, "debit", 3_500_000, date(2026, 10, 15), "CITY ELECTRICITY BOARD", "BP2610150098812",
        balance=56_500_000)
    return check_drift(env.conn, 1, source="alert", clock=env.clock, reported_paise=56_500_000,
                       reported_at=ALERT_AT)


def run_jobs(env, handlers):
    while process_one(env.conn, handlers, clock=env.clock, settings=env.settings, app_config=env.app_config):
        pass


# --- the writer owns bank_account (AC7) --------------------------------------------------


@pytest.mark.parametrize("frm, to, actor", [
    ("OK", "CHECKING", "reconciler"), ("CHECKING", "OK", "reconciler"), ("CHECKING", "ASK_OWNER", "reconciler"),
])
def test_drift_moves_follow_the_table(env, frm, to, actor):
    env.conn.execute("UPDATE bank_account SET drift_status = ? WHERE id = 1", (frm,))
    env.conn.commit()
    after = writer.set_drift_status(1, to, actor, "why", "bank_account:1", conn=env.conn, clock=env.clock)
    assert after["drift_status"] == to
    assert drift_events(env) == [(f"BANK_ACCOUNT_{to}", "reconciler")]


@pytest.mark.parametrize("frm, to, actor, error", [
    ("OK", "ASK_OWNER", "reconciler", IllegalTransition),
    ("ASK_OWNER", "CHECKING", "reconciler", IllegalTransition),
    ("OK", "CHECKING", "pipeline", ActorNotAllowed),
    ("OK", "CHECKING", "planner", ActorNotAllowed),
    ("OK", "CHECKING", "agent:case:1", AgentActorRefused),
    ("CHECKING", "OK", "agent:case:1", AgentActorRefused),
    ("ASK_OWNER", "OK", "owner:1", IllegalTransition),  # only through confirm_balance
])
def test_other_drift_moves_are_refused_and_change_nothing(env, frm, to, actor, error):
    env.conn.execute("UPDATE bank_account SET drift_status = ? WHERE id = 1", (frm,))
    env.conn.commit()
    with pytest.raises(error):
        writer.set_drift_status(1, to, actor, "why", None, conn=env.conn, clock=env.clock)
    assert account(env)["drift_status"] == frm
    assert drift_events(env) == []


def test_only_the_reconciler_records_a_reported_balance(env):
    for actor, error in (("pipeline", ActorNotAllowed), ("owner:1", ActorNotAllowed),
                         ("agent:case:1", AgentActorRefused)):
        with pytest.raises(error):
            writer.record_reported_balance(1, 100, ALERT_AT.isoformat(), actor, "x", None, conn=env.conn,
                                           reconciled=False, clock=env.clock)
    assert account(env)["reported_balance_paise"] is None


def test_an_older_report_never_replaces_a_newer_one(env):
    kw = dict(conn=env.conn, reconciled=False, clock=env.clock)
    writer.record_reported_balance(1, 500, ALERT_AT.isoformat(), "reconciler", "x", None, **kw)
    writer.record_reported_balance(1, 400, (ALERT_AT - timedelta(hours=1)).isoformat(), "reconciler", "x",
                                   None, **kw)
    assert account(env)["reported_balance_paise"] == 500
    assert drift_events(env) == [("BANK_ACCOUNT_REPORTED_BALANCE", "reconciler")]


# --- the check -----------------------------------------------------------------------


def test_an_alert_that_agrees_marks_the_account_reconciled(env):
    txn(env, "debit", 3_500_000, date(2026, 10, 15), "CITY ELECTRICITY BOARD")
    r = check_drift(env.conn, 1, source="alert", clock=env.clock, reported_paise=58_500_000,
                    reported_at=ALERT_AT)
    a = account(env)
    assert (a["drift_status"], a["reported_balance_paise"], a["last_reconciled_at"]) == (
        "OK", 58_500_000, ALERT_AT.isoformat(),
    )
    assert r.recheck_at is None and not r.case_ids


def test_an_alert_mismatch_waits_for_the_23_00_recheck(env):
    r = _missed_debit_alert(env)
    assert r.recheck_at == datetime(2026, 10, 15, 23, 0, tzinfo=TIMEZONE)
    a = account(env)
    assert (a["drift_status"], a["reported_balance_paise"], a["last_reconciled_at"]) == (
        "OK", 56_500_000, None,
    )
    assert cases(env) == []


def test_an_alert_after_23_00_is_rechecked_the_next_night(env):
    txn(env, "debit", 3_500_000, date(2026, 10, 15), "X")
    late = datetime(2026, 10, 15, 23, 30, tzinfo=TIMEZONE)
    r = check_drift(env.conn, 1, source="alert", clock=env.clock, reported_paise=1, reported_at=late)
    assert r.recheck_at == datetime(2026, 10, 16, 23, 0, tzinfo=TIMEZONE)


def test_a_mismatch_still_there_at_23_00_sets_checking_and_opens_a_drift_case(env):
    _missed_debit_alert(env)
    r = check_drift(env.conn, 1, source="recheck", clock=env.clock)
    assert account(env)["drift_status"] == "CHECKING"
    (case,) = cases(env)
    assert (case["kind"], case["subject_ref"], case["stake_paise"], case["thinking"]) == (
        "drift", "bank_account:1", 2_000_000, "medium",
    )
    assert "Gap (reported minus calculated): -₹20,000" in case["case_file_md"]
    assert r.replan and r.case_ids == [case["id"]]


def test_a_gap_that_closes_before_23_00_never_becomes_checking(env):
    _missed_debit_alert(env)
    txn(env, "debit", 2_000_000, date(2026, 10, 15), "BANK CHARGES")  # the missing alert arrives
    r = check_drift(env.conn, 1, source="recheck", clock=env.clock)
    assert account(env)["drift_status"] == "OK"
    assert cases(env) == [] and not r.replan


def test_a_statement_mismatch_is_acted_on_at_once(env):
    r = check_drift(env.conn, 1, source="statement", clock=env.clock, reported_paise=60_000_000,
                    reported_at=ALERT_AT)
    assert account(env)["drift_status"] == "CHECKING"
    assert r.recheck_at is None and len(cases(env)) == 1


def test_only_transactions_on_or_before_the_reported_day_count(env):
    txn(env, "debit", 1_000_000, date(2026, 10, 16), "LATER")  # after the report: not in that balance
    check_drift(env.conn, 1, source="statement", clock=env.clock, reported_paise=62_000_000,
                reported_at=ALERT_AT)
    assert account(env)["drift_status"] == "OK"


def test_a_found_transaction_closes_the_gap_and_the_account_returns_to_ok(env):
    _missed_debit_alert(env)
    check_drift(env.conn, 1, source="recheck", clock=env.clock)
    assert account(env)["drift_status"] == "CHECKING"
    found = txn(env, "debit", 2_000_000, date(2026, 10, 15), "BANK CHARGES")  # e.g. recovered from Gmail
    queue.enqueue(env.conn, kind="reconcile_txn", payload={"bank_txn_id": found}, clock=env.clock)
    env.conn.commit()
    run_jobs(env, {"reconcile_txn": handle_reconcile_txn})
    assert account(env)["drift_status"] == "OK"
    assert ("BANK_ACCOUNT_OK", "reconciler") in drift_events(env)
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'replan'").fetchone()[0] == 1


# --- the 23:00 recheck as a job ----------------------------------------------------------


def test_the_recheck_job_waits_until_23_00(env):
    queue.enqueue(env.conn, kind="drift_check", clock=env.clock, payload={
        "account_id": 1, "source": "alert", "reported_paise": 56_500_000, "reported_at": ALERT_AT.isoformat(),
    })
    txn(env, "debit", 3_500_000, date(2026, 10, 15), "CITY ELECTRICITY BOARD")
    env.conn.commit()
    run_jobs(env, {"drift_check": handle_drift_check})
    (recheck,) = env.conn.execute("SELECT * FROM job WHERE status = 'queued' AND kind = 'drift_check'").fetchall()
    assert recheck["run_after"] == "2026-10-15T23:00:00+05:30"
    assert account(env)["drift_status"] == "OK"

    env.clock.advance(timedelta(hours=9, minutes=59))  # 22:59: not yet
    run_jobs(env, {"drift_check": handle_drift_check})
    assert account(env)["drift_status"] == "OK"
    env.clock.advance(timedelta(minutes=1))
    run_jobs(env, {"drift_check": handle_drift_check})
    assert account(env)["drift_status"] == "CHECKING"
    queued = sorted(r[0] for r in env.conn.execute("SELECT kind FROM job WHERE status = 'queued'"))
    assert queued == ["replan", "run_case"]  # run_case waits for CHG-008


# --- AC6: the plan uses the lower balance while drift is unresolved -------------------------


def test_while_checking_the_stored_plan_starts_from_the_lower_balance(env):
    _missed_debit_alert(env)
    check_drift(env.conn, 1, source="recheck", clock=env.clock)
    run_id = replan(env.conn, 1, triggered_by="test", clock=env.clock)
    opening = env.conn.execute("SELECT opening_cash_paise FROM plan_run WHERE id = ?", (run_id,)).fetchone()[0]
    assert opening == 56_500_000  # reported ₹5,65,000, not the calculated ₹5,85,000


def test_once_ok_the_plan_uses_the_calculated_balance_again(env):
    _missed_debit_alert(env)
    run_id = replan(env.conn, 1, triggered_by="test", clock=env.clock)  # still OK: waiting for 23:00
    opening = env.conn.execute("SELECT opening_cash_paise FROM plan_run WHERE id = ?", (run_id,)).fetchone()[0]
    assert opening == 58_500_000


# --- confirm_balance (step 6) ---------------------------------------------------------------


def _ask_owner(env):
    _missed_debit_alert(env)
    check_drift(env.conn, 1, source="recheck", clock=env.clock)
    writer.set_drift_status(1, "ASK_OWNER", "reconciler", "agent gave up", None, conn=env.conn, clock=env.clock)


def test_confirm_balance_writes_an_owner_adjustment_and_returns_to_ok(env):
    _ask_owner(env)
    adj = writer.confirm_balance(1, 56_500_000, "owner:1", "the bank app shows ₹5,65,000", "owner_question:1",
                                 conn=env.conn, clock=env.clock)
    assert (adj.status, adj.direction, adj.amount_paise, adj.txn_date) == (
        "ADJUSTMENT", "debit", 2_000_000, date(2026, 10, 15),
    )
    a = account(env)
    assert (a["drift_status"], a["reported_balance_paise"]) == ("OK", 56_500_000)
    assert env.conn.execute("SELECT calculated_balance_paise FROM account_balance").fetchone()[0] == 56_500_000
    created = env.conn.execute(
        "SELECT actor FROM event WHERE event_type = 'BANK_TXN_CREATED' AND entity_id = ?", (adj.id,)
    ).fetchone()[0]
    assert created == "owner:1"
    assert drift_events(env)[-1] == ("BANK_ACCOUNT_OK", "owner:1")


def test_confirming_the_calculated_figure_writes_no_adjustment(env):
    _ask_owner(env)
    assert writer.confirm_balance(1, 58_500_000, "owner:1", "x", None, conn=env.conn, clock=env.clock) is None
    assert account(env)["drift_status"] == "OK"


@pytest.mark.parametrize("actor, error", [
    ("reconciler", ActorNotAllowed), ("agent:case:1", AgentActorRefused), ("owner:3", ActorNotAllowed),
])
def test_only_the_businesss_owner_confirms_a_balance(env, actor, error):
    _ask_owner(env)
    with pytest.raises(error):
        writer.confirm_balance(1, 1, actor, "x", None, conn=env.conn, clock=env.clock)
    assert account(env)["drift_status"] == "ASK_OWNER"


@pytest.mark.parametrize("state", ["OK", "CHECKING"])
def test_confirm_balance_only_answers_an_ask_owner_account(env, state):
    env.conn.execute("UPDATE bank_account SET drift_status = ? WHERE id = 1", (state,))
    env.conn.commit()
    with pytest.raises(IllegalTransition):
        writer.confirm_balance(1, 1, "owner:1", "x", None, conn=env.conn, clock=env.clock)
    assert env.conn.execute("SELECT COUNT(*) FROM bank_txn").fetchone()[0] == 0
