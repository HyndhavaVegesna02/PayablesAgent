"""Failures and reversals (batch 2 plan, CHG-005 AC2; TDD Part 2, "Failures
and reversals"): a failure or return email reopens the bill it is about,
reverses any original debit and asks for a replan."""

import json
from datetime import date

import pytest

from app.jobs import queue
from app.jobs.reconcile import handle_reconcile_failure
from app.ledger.reconcile import handle_failure, match_debit
from app.worker import process_one
from tests.reconcile_helpers import PAPER, cases, plan_and_approve, status, txn
from tests.worker_helpers import make_env

REF = "N286261234567"


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


def notice(env, *, amount=18_000_000, reference=REF, failed_on="2026-10-14", status_="VALID"):
    doc = env.conn.execute(
        "INSERT INTO source_document (business_id, kind, external_ref, content_sha256, received_at, status) "
        "VALUES (1, 'email', ?, ?, '2026-10-14T10:21:33+05:30', 'PROCESSED')",
        (f"<n{amount}{reference}{failed_on}>", f"sha-{amount}-{reference}-{failed_on}"),
    ).lastrowid
    record = {"account_id": 1, "amount_paise": amount, "failure_date": failed_on,
              "original_reference": reference, "reason": "Beneficiary account closed",
              "dedup_key": f"failure:1:{failed_on}:{amount}:{reference}"}
    cand = env.conn.execute(
        "INSERT INTO candidate (source_document_id, record_type, payload_json, status, created_by, created_at) "
        "VALUES (?, 'txn', ?, ?, 'pipeline', '2026-10-14T10:22:00+05:30')",
        (doc, json.dumps({"doc_type": "failure_notice", "record": record, "dedup_key": record["dedup_key"]}),
         status_),
    ).lastrowid
    env.conn.commit()
    return cand


def _fail(env, cand):
    return handle_failure(env.conn, cand, window_days=3, clock=env.clock)


def _paid_paper(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, date(2026, 10, 12), "ASHIRWAD PAPER SUPPLIERS", REF)
    match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert status(env, "payable", PAPER) == "PAID"
    return t


def test_a_return_email_reopens_a_paid_bill_and_reverses_its_debit(env):
    t = _paid_paper(env)
    result = _fail(env, notice(env))
    assert result.replan and result.case_ids == []
    assert status(env, "payable", PAPER) == "REOPENED"
    assert status(env, "bank_txn", t) == "REVERSED"
    ev = env.conn.execute(
        "SELECT event_type, actor, source_ref, reason FROM event WHERE event_type IN "
        "('PAYABLE_REOPENED', 'BANK_TXN_REVERSED') ORDER BY id"
    ).fetchall()
    assert [(e["event_type"], e["actor"]) for e in ev] == [
        ("BANK_TXN_REVERSED", "reconciler"), ("PAYABLE_REOPENED", "reconciler"),
    ]
    assert "Beneficiary account closed" in ev[1]["reason"]


def test_the_reversed_debit_no_longer_counts_in_the_balance(env):
    _paid_paper(env)
    before = env.conn.execute("SELECT calculated_balance_paise FROM account_balance").fetchone()[0]
    _fail(env, notice(env))
    after = env.conn.execute("SELECT calculated_balance_paise FROM account_balance").fetchone()[0]
    assert (before, after) == (44_000_000, 62_000_000)


def test_a_failure_before_the_debit_was_seen_reopens_the_approved_bill(env):
    plan_and_approve(env, PAPER)  # PAYMENT_EXPECTED, planned Mon 12; no debit arrived
    result = _fail(env, notice(env, reference=None, failed_on="2026-10-13"))
    assert result.replan
    assert status(env, "payable", PAPER) == "REOPENED"


def test_a_paid_bill_needs_the_reference_to_match(env):
    _paid_paper(env)
    result = _fail(env, notice(env, reference="N999999999999"))
    assert status(env, "payable", PAPER) == "PAID"
    (case,) = cases(env)
    assert case["kind"] == "failed_payment" and result.case_ids == [case["id"]]
    assert not result.replan


def test_a_failure_that_matches_no_bill_opens_a_failed_payment_case(env):
    cand = notice(env, amount=7_700_000)
    result = _fail(env, cand)
    (case,) = cases(env)
    assert (case["kind"], case["subject_ref"], case["stake_paise"]) == ("failed_payment", f"candidate:{cand}", 7_700_000)
    assert result.case_ids == [case["id"]] and not result.replan
    assert "Bills that could match: none" in case["case_file_md"]


def test_a_failure_for_a_debit_that_was_never_matched_reverses_it(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, date(2026, 10, 12), "SOMEONE ELSE", REF)
    match_debit(env.conn, t, window_days=3, clock=env.clock)  # no name match: bill to REVIEW
    assert status(env, "payable", PAPER) == "REVIEW"

    result = _fail(env, notice(env))
    assert status(env, "bank_txn", t) == "REVERSED"  # UNMATCHED -> REVERSED (Q7)
    assert status(env, "payable", PAPER) == "REVIEW"  # the owner resolves REVIEW
    assert result.replan
    assert [c["kind"] for c in cases(env)] == ["ambiguous_match", "failed_payment"]


def test_the_job_queues_the_replan(env):
    _paid_paper(env)
    cand = notice(env)
    queue.enqueue(env.conn, kind="reconcile_failure", payload={"candidate_id": cand}, clock=env.clock)
    env.conn.commit()
    assert process_one(env.conn, {"reconcile_failure": handle_reconcile_failure}, clock=env.clock,
                       settings=env.settings, app_config=env.app_config)
    kinds = [r[0] for r in env.conn.execute("SELECT kind FROM job WHERE status = 'queued'")]
    assert kinds == ["replan", "send_alert"]  # the owner is told the payment came back (CHG-010b)
    (payload,) = env.conn.execute("SELECT payload_json FROM job WHERE kind = 'replan'").fetchone()
    last_event = env.conn.execute("SELECT MAX(id) FROM event").fetchone()[0]
    assert json.loads(payload) == {"business_id": 1, "triggered_by": f"event:{last_event}"}


def test_the_job_refuses_a_candidate_that_is_not_a_valid_notice(env):
    cand = notice(env, status_="AWAITING_OWNER")
    queue.enqueue(env.conn, kind="reconcile_failure", payload={"candidate_id": cand}, clock=env.clock)
    env.conn.commit()
    process_one(env.conn, {"reconcile_failure": handle_reconcile_failure}, clock=env.clock,
                settings=env.settings, app_config=env.app_config)
    assert env.conn.execute("SELECT status FROM job").fetchone()[0] == "dead"
