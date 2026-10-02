"""TDD Phase 4 exit (batch 2 plan, CHG-005 AC8 and AC9): the three scenarios
end to end through the real worker on the seeded worked example, with the
fake AI reading the test inbox. The web app does not exist yet, so the
owner's approval is a writer call, as it will be from the app.

1. A debit alert reconciles against a payment approved through the planner.
2. A return email reopens the bill, reverses the debit and replans.
3. A missing alert (the balance is short) puts the account into CHECKING.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from app.clock import TIMEZONE
from app.jobs import queue
from app.ledger import writer
from app.ledger.writer import EntityRef
from app.trace import view
from app.worker import default_handlers
from tests.fake_ai import fixture_backend
from tests.reconcile_helpers import PAPER, cases, status
from tests.worker_helpers import deliver, make_mail_env, run_all

DEBIT = "01-debit-ashirwad-paper.eml"
RETURN = "03-return-ashirwad-paper.eml"
SHORT = "04-debit-city-electricity-balance-short.eml"
RESENT = "06-debit-ashirwad-paper-resent.eml"


@pytest.fixture
def env(tmp_path):
    e = make_mail_env(tmp_path)  # Mon 12 Oct 2026, 09:00
    yield e
    e.conn.close()


def at(env, day, hour, minute=0):
    target = datetime(2026, 10, day, hour, minute, tzinfo=TIMEZONE)
    env.clock.advance(target - env.clock.now())


def enqueue(env, kind, payload=None):
    queue.enqueue(env.conn, kind=kind, payload=payload or {}, clock=env.clock)
    env.conn.commit()


def current_plan(env):
    return env.conn.execute("SELECT * FROM plan_run WHERE business_id = 1 AND is_current = 1").fetchone()


def plan_line(env, payable_id):
    return env.conn.execute(
        "SELECT decision, pay_on FROM plan_line WHERE plan_run_id = ? AND payable_id = ?",
        (current_plan(env)["id"], payable_id),
    ).fetchone()


def approve(env, payable_id):
    v = env.conn.execute("SELECT version FROM payable WHERE id = ?", (payable_id,)).fetchone()[0]
    writer.transition(EntityRef("payable", payable_id), "PAYMENT_EXPECTED", "owner:1",
                      "owner approved the plan", f"plan_run:{current_plan(env)['id']}", conn=env.conn,
                      expected_version=v, clock=env.clock)


def _plan_and_approve_paper(env, handlers):
    enqueue(env, "monday_plan", {"business_id": 1})
    run_all(env, handlers)
    assert tuple(plan_line(env, PAPER)) == ("PAY", "2026-10-12")
    assert status(env, "payable", PAPER) == "PLANNED"
    approve(env, PAPER)


def test_scenario_1_a_debit_alert_reconciles_against_the_approved_payment(env, monkeypatch, capsys):
    handlers = default_handlers(fixture_backend(DEBIT))
    _plan_and_approve_paper(env, handlers)

    at(env, 12, 12)
    deliver(env, DEBIT)
    enqueue(env, "poll_mail")
    run_all(env, handlers)

    (txn,) = env.conn.execute("SELECT * FROM bank_txn").fetchall()
    assert (txn["status"], txn["amount_paise"]) == ("MATCHED", 18_000_000)
    assert status(env, "payable", PAPER) == "PAID"
    assert env.conn.execute("SELECT matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()[0] == txn["id"]
    # the alert's ₹4,40,000 agrees with the ledger, so the account is reconciled
    acct = env.conn.execute("SELECT * FROM bank_account WHERE id = 1").fetchone()
    assert (acct["drift_status"], acct["reported_balance_paise"]) == ("OK", 44_000_000)
    assert acct["last_reconciled_at"] == "2026-10-12T11:42:07+05:30"
    # the match asked for a replan, and it ran: the paid bill has left the plan
    plan = current_plan(env)
    assert plan["triggered_by"].startswith("event:")
    assert plan["opening_cash_paise"] == 44_000_000
    assert plan_line(env, PAPER) is None
    assert cases(env) == []
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE status <> 'done'").fetchone()[0] == 0

    # the debit's trace: sort and extract, with tokens and cost, then validation
    process_job = env.conn.execute("SELECT id FROM job WHERE kind = 'process_document'").fetchone()[0]
    monkeypatch.setenv("TRACE_DIR", env.settings.trace_dir)
    capsys.readouterr()
    assert view.main([f"job-{process_job}-attempt-1"]) == 0
    trace = capsys.readouterr().out
    assert "tool=ai.call:sort" in trace and "tool=ai.call:extract:bank_alert" in trace
    assert "tokens=input:1000/output:100/thoughts:50" in trace and "tool=validate" in trace


def test_scenario_2_a_return_email_reopens_the_bill_and_replans(env):
    handlers = default_handlers(fixture_backend(DEBIT, RETURN))
    _plan_and_approve_paper(env, handlers)
    at(env, 12, 12)
    deliver(env, DEBIT)
    enqueue(env, "poll_mail")
    run_all(env, handlers)
    assert status(env, "payable", PAPER) == "PAID"

    at(env, 14, 11)  # Wed 14 Oct: the bank returns the payment
    deliver(env, RETURN)
    enqueue(env, "poll_mail")
    run_all(env, handlers)

    debit_id = env.conn.execute("SELECT id FROM bank_txn").fetchone()[0]
    assert status(env, "bank_txn", debit_id) == "REVERSED"
    reopened = env.conn.execute(
        "SELECT actor, source_ref FROM event WHERE event_type = 'PAYABLE_REOPENED'"
    ).fetchone()
    assert reopened["actor"] == "reconciler" and reopened["source_ref"].startswith("candidate:")
    # the replan ran: ₹1,80,000 is back in the balance and the bill is planned
    # again for the next payment day, Thu 15 Oct (it is due Wed 14)
    plan = current_plan(env)
    assert plan["opening_cash_paise"] == 62_000_000
    assert tuple(plan_line(env, PAPER)) == ("PAY", "2026-10-15")
    row = env.conn.execute("SELECT status, planned_date FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert tuple(row) == ("PLANNED", "2026-10-15")
    assert cases(env) == []


def test_scenario_3_a_missing_alert_puts_the_account_into_checking(env):
    handlers = default_handlers(fixture_backend(SHORT))
    at(env, 15, 13)
    deliver(env, SHORT)
    enqueue(env, "poll_mail")
    run_all(env, handlers)

    # nothing was approved for ₹35,000, so the debit is unknown, and the ₹20,000
    # gap waits for the 23:00 recheck before anything else happens
    acct = env.conn.execute("SELECT * FROM bank_account WHERE id = 1").fetchone()
    assert (acct["drift_status"], acct["reported_balance_paise"]) == ("OK", 56_500_000)
    assert [c["kind"] for c in cases(env)] == ["unknown_txn"]
    (recheck,) = env.conn.execute(
        "SELECT run_after FROM job WHERE kind = 'drift_check' AND status = 'queued'"
    ).fetchall()
    assert recheck[0] == "2026-10-15T23:00:00+05:30"

    at(env, 15, 23)
    run_all(env, handlers)
    assert env.conn.execute("SELECT drift_status FROM bank_account WHERE id = 1").fetchone()[0] == "CHECKING"
    drift = [c for c in cases(env) if c["kind"] == "drift"]
    assert len(drift) == 1 and drift[0]["stake_paise"] == 2_000_000
    # the replan after CHECKING plans from the lower balance
    assert current_plan(env)["opening_cash_paise"] == 56_500_000
    # the agent's cases wait for CHG-008
    waiting = sorted(r[0] for r in env.conn.execute("SELECT kind FROM job WHERE status = 'queued'"))
    assert waiting == ["run_case", "run_case"]


def test_redelivered_alerts_leave_one_transaction_and_one_match(env):
    handlers = default_handlers(fixture_backend(DEBIT, RESENT))
    _plan_and_approve_paper(env, handlers)
    at(env, 12, 12)
    deliver(env, DEBIT, RESENT)
    # the same file again under another name: identical bytes
    inbox = Path(env.settings.test_inbox_path)
    shutil.copy(inbox / DEBIT, inbox / "01-again.eml")
    enqueue(env, "poll_mail")
    run_all(env, handlers)
    enqueue(env, "poll_mail")  # and the same messages seen on a second poll
    run_all(env, handlers)

    assert env.conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0] == 2  # 01 and 06
    assert env.conn.execute("SELECT COUNT(*) FROM bank_txn").fetchone()[0] == 1
    assert env.conn.execute("SELECT COUNT(*) FROM event WHERE event_type = 'PAYABLE_PAID'").fetchone()[0] == 1
    assert env.conn.execute("SELECT COUNT(*) FROM event WHERE event_type = 'BANK_TXN_MATCHED'").fetchone()[0] == 1
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'reconcile_txn'").fetchone()[0] == 1
    dup = env.conn.execute("SELECT status, checks_json FROM candidate ORDER BY id").fetchall()[1]
    assert dup["status"] == "INVALID"
    assert json.loads(dup["checks_json"])["duplicates"].startswith("failed: same as bank transaction")
    assert status(env, "payable", PAPER) == "PAID"
    assert cases(env) == []
