"""A bill the owner marked PAID before its bank debit arrived (batch 3 plan,
PO decision D12): the plan keeps subtracting it until the debit links to it,
the debit links instead of opening an unknown_txn case, and the money is
subtracted once."""

from datetime import date

import pytest

from app.db.read import build_snapshot
from app.domain.states import ActorNotAllowed, IllegalTransition
from app.jobs.replan import replan
from app.ledger import writer
from app.ledger.reconcile import match_debit
from app.ledger.writer import EntityRef
from app.planner.plan import plan
from tests.reconcile_helpers import PAPER, cases, plan_and_approve, status, txn
from tests.worker_helpers import make_env

OCT = lambda d: date(2026, 10, d)  # noqa: E731


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


def _owner_marks_paid(env, bill_id):
    v = env.conn.execute("SELECT version FROM payable WHERE id = ?", (bill_id,)).fetchone()[0]
    writer.transition(EntityRef("payable", bill_id), "PAID", "owner:1", "owner marked paid", None,
                      conn=env.conn, expected_version=v, clock=env.clock)


def _lowest(env):
    run_id = replan(env.conn, 1, triggered_by="test", clock=env.clock)
    return env.conn.execute("SELECT lowest_balance_paise, lowest_on FROM plan_run WHERE id = ?",
                            (run_id,)).fetchone()


def test_marking_paid_before_the_debit_does_not_overstate_cash(env):
    plan_and_approve(env, PAPER)
    before = tuple(_lowest(env))
    _owner_marks_paid(env, PAPER)
    assert tuple(_lowest(env)) == before == (18_300_000, "2026-10-22")


def test_the_late_debit_links_to_the_paid_bill_instead_of_opening_a_case(env):
    plan_and_approve(env, PAPER)
    _owner_marks_paid(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS")
    result = match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert result.outcome == f"linked to bill {PAPER}, already PAID" and result.replan
    assert cases(env) == []
    assert status(env, "payable", PAPER) == "PAID" and status(env, "bank_txn", t) == "MATCHED"
    row = env.conn.execute("SELECT matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert row[0] == t
    ev = env.conn.execute("SELECT actor, event_type FROM event WHERE entity = 'payable' AND entity_id = ? "
                          "ORDER BY id DESC LIMIT 1", (PAPER,)).fetchone()
    assert tuple(ev) == ("reconciler", "PAYABLE_PAYMENT_LINKED")


def test_the_linked_bill_is_subtracted_once_by_its_debit(env):
    plan_and_approve(env, PAPER)
    _owner_marks_paid(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS")
    match_debit(env.conn, t, window_days=3, clock=env.clock)
    s = build_snapshot(env.conn, 1, env.clock.today())
    assert PAPER not in {p.payable_id for p in s.payables}
    assert s.accounts[0].calculated_paise == 62_000_000 - 18_000_000
    assert plan(s).lowest_balance_paise == 18_300_000


def test_a_second_debit_of_the_same_amount_does_not_relink(env):
    plan_and_approve(env, PAPER)
    _owner_marks_paid(env, PAPER)
    first = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS", "REF1")
    match_debit(env.conn, first, window_days=3, clock=env.clock)
    second = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS", "REF2")
    result = match_debit(env.conn, second, window_days=3, clock=env.clock)
    assert result.outcome == "no bill matches: debit stays UNMATCHED"
    assert env.conn.execute("SELECT matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()[0] == first
    with pytest.raises(IllegalTransition, match="already linked"):
        writer.link_payment(PAPER, second, "reconciler", "again", None, conn=env.conn, clock=env.clock)


def test_only_the_reconciler_links_a_payment_and_only_to_a_paid_bill(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS")
    with pytest.raises(ActorNotAllowed):
        writer.link_payment(PAPER, t, "owner:1", "x", None, conn=env.conn, clock=env.clock)
    with pytest.raises(IllegalTransition, match="not PAID"):
        writer.link_payment(PAPER, t, "reconciler", "x", None, conn=env.conn, clock=env.clock)


def test_an_owner_paid_bill_and_an_approved_one_of_the_same_amount_are_ambiguous(env):
    # Two candidates across PAYMENT_EXPECTED and PAID-unmatched: REVIEW for the
    # approved one and a case; the owner-paid bill stays PAID (it cannot go to REVIEW).
    plan_and_approve(env, PAPER)
    _owner_marks_paid(env, PAPER)
    from app.domain.models import PayableNew

    twin = writer.create_payable(PayableNew(business_id=1, party_id=1, amount_paise=18_000_000,
                                            due_date=OCT(14), priority="normal"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "CONFIRMED", "owner:1", "t", None, conn=env.conn,
                      expected_version=twin.version, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "PLANNED", "planner", "t", None, conn=env.conn,
                      fields={"planned_date": OCT(12)}, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "PAYMENT_EXPECTED", "owner:1", "t", None, conn=env.conn,
                      expected_version=twin.version + 2, clock=env.clock)
    t = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS")
    result = match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert result.outcome.startswith("ambiguous") and len(result.case_ids) == 1
    assert status(env, "payable", PAPER) == "PAID" and status(env, "payable", twin.id) == "REVIEW"
    assert "(PAID)" in cases(env)[0]["case_file_md"]
