"""The reconcile job handlers through the real worker (batch 2 review round 1):
each handler's writes and the jobs it queues land in one transaction, a
re-run after a crash changes nothing twice, and a gap closes after a reversal."""

import json
from datetime import date, datetime

import pytest

from app.clock import TIMEZONE
from app.jobs import queue
from app.jobs.reconcile import handle_drift_check, handle_reconcile_failure, handle_reconcile_txn
from app.ledger import reconcile, writer
from app.ledger.reconcile import check_drift, match_debit
from app.worker import process_one
from tests.reconcile_helpers import PAPER, cases, plan_and_approve, status, txn
from tests.test_reconcile_failure import REF, notice
from tests.worker_helpers import make_env

HANDLERS = {"reconcile_txn": handle_reconcile_txn, "reconcile_failure": handle_reconcile_failure,
            "drift_check": handle_drift_check}


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


def run(env, kind, payload):
    job_id = queue.enqueue(env.conn, kind=kind, payload=payload, clock=env.clock)
    env.conn.commit()
    assert process_one(env.conn, HANDLERS, clock=env.clock, settings=env.settings, app_config=env.app_config)
    return env.conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()


def queued(env, kind):
    return env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = ? AND status = 'queued'", (kind,)).fetchone()[0]


def fail_on(monkeypatch, to_state):
    real = writer.transition

    def transition(ref, to, *a, **kw):
        if to == to_state:
            raise RuntimeError(f"crash writing {to}")
        return real(ref, to, *a, **kw)

    monkeypatch.setattr(writer, "transition", transition)


def test_a_crash_between_matched_and_paid_leaves_neither_and_queues_nothing(env, monkeypatch):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, date(2026, 10, 12), "ASHIRWAD PAPER SUPPLIERS", REF)
    fail_on(monkeypatch, "PAID")
    j = run(env, "reconcile_txn", {"bank_txn_id": t})
    assert (j["status"], j["attempts"]) == ("queued", 1)  # retried later
    assert (status(env, "bank_txn", t), status(env, "payable", PAPER)) == ("UNMATCHED", "PAYMENT_EXPECTED")
    assert queued(env, "replan") == 0


def test_a_crash_between_reversed_and_reopened_leaves_neither(env, monkeypatch):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, date(2026, 10, 12), "ASHIRWAD PAPER SUPPLIERS", REF)
    match_debit(env.conn, t, window_days=3, clock=env.clock)
    cand = notice(env)
    fail_on(monkeypatch, "REOPENED")
    run(env, "reconcile_failure", {"candidate_id": cand})
    assert (status(env, "bank_txn", t), status(env, "payable", PAPER)) == ("MATCHED", "PAID")
    assert status(env, "candidate", cand) == "VALID"
    assert queued(env, "replan") == 0


def test_a_crash_while_opening_the_drift_case_leaves_the_account_ok(env, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("crash opening the case")

    monkeypatch.setattr(reconcile, "open_case", boom)
    run(env, "drift_check", {"account_id": 1, "source": "statement", "reported_paise": 1,
                             "reported_at": "2026-10-12T18:00:00+05:30"})
    acct = env.conn.execute("SELECT drift_status, reported_balance_paise FROM bank_account").fetchone()
    assert tuple(acct) == ("OK", None)  # the reported balance was rolled back too
    assert queued(env, "run_case") == 0 and queued(env, "replan") == 0


def test_a_failure_job_run_twice_reopens_once_and_opens_no_case(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, date(2026, 10, 12), "ASHIRWAD PAPER SUPPLIERS", REF)
    match_debit(env.conn, t, window_days=3, clock=env.clock)
    cand = notice(env)
    run(env, "reconcile_failure", {"candidate_id": cand})
    again = run(env, "reconcile_failure", {"candidate_id": cand})  # e.g. requeued after a crash
    assert again["status"] == "done"
    assert status(env, "candidate", cand) == "ACCEPTED"
    assert cases(env) == []
    assert env.conn.execute("SELECT COUNT(*) FROM event WHERE event_type = 'PAYABLE_REOPENED'").fetchone()[0] == 1


def test_an_unknown_debit_run_twice_opens_one_case(env):
    t = txn(env, "debit", 1_234_500, date(2026, 10, 12), "MYSTERY CO")
    run(env, "reconcile_txn", {"bank_txn_id": t})
    run(env, "reconcile_txn", {"bank_txn_id": t})
    assert len(cases(env)) == 1
    assert queued(env, "run_case") == 1  # the idempotency key keeps one


def test_an_unknown_debit_asks_for_a_replan(env):
    t = txn(env, "debit", 1_234_500, date(2026, 10, 12), "MYSTERY CO")
    run(env, "reconcile_txn", {"bank_txn_id": t})
    assert queued(env, "replan") == 1


def test_a_reversal_while_checking_rechecks_the_gap(env):
    # The bank reports ₹6,20,000 but a returned ₹1,80,000 debit is still counted:
    # CHECKING. Reversing that debit closes the gap.
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, date(2026, 10, 12), "ASHIRWAD PAPER SUPPLIERS", REF)
    match_debit(env.conn, t, window_days=3, clock=env.clock)
    check_drift(env.conn, 1, source="statement", clock=env.clock, reported_paise=62_000_000,
                reported_at=datetime(2026, 10, 14, 18, 0, tzinfo=TIMEZONE))
    assert env.conn.execute("SELECT drift_status FROM bank_account").fetchone()[0] == "CHECKING"
    run(env, "reconcile_failure", {"candidate_id": notice(env)})
    assert env.conn.execute("SELECT drift_status FROM bank_account").fetchone()[0] == "OK"


@pytest.mark.parametrize("payload", [
    {"account_id": 1, "source": "alert"},
    {"account_id": 1, "source": "statement", "reported_paise": 5},
    {"account_id": 1, "source": "sideways"},
    {"account_id": 99, "source": "recheck"},
])
def test_a_malformed_drift_check_dead_letters_at_once(env, payload):
    j = run(env, "drift_check", payload)
    assert (j["status"], j["attempts"]) == ("dead", 1)


def test_the_replan_is_labelled_with_this_businesss_latest_event(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, date(2026, 10, 12), "ASHIRWAD PAPER SUPPLIERS", REF)
    run(env, "reconcile_txn", {"bank_txn_id": t})
    (payload,) = env.conn.execute("SELECT payload_json FROM job WHERE kind = 'replan'").fetchone()
    last = env.conn.execute("SELECT MAX(id) FROM event WHERE business_id = 1").fetchone()[0]
    assert json.loads(payload)["triggered_by"] == f"event:{last}"
