"""Matching debits and credits (batch 2 plan, CHG-005 AC1, AC3, AC4; TDD Part 2,
"A new debit" steps 1-5 and "A new credit"), on the seeded worked example."""

from datetime import date

import pytest

from app.domain.names import name_matches, normalise_name
from app.ledger.reconcile import match_credit, match_debit
from tests.reconcile_helpers import (
    ELEC,
    KAVERI,
    NANDI,
    PAPER,
    cases,
    plan_and_approve,
    status,
    txn,
)
from tests.worker_helpers import make_env

OCT = lambda d: date(2026, 10, d)  # noqa: E731


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


def _debit(env, txn_id):
    return match_debit(env.conn, txn_id, window_days=3, clock=env.clock)


def _credit(env, txn_id):
    return match_credit(env.conn, txn_id, window_days=3, clock=env.clock)


# --- names ------------------------------------------------------------------------


@pytest.mark.parametrize("raw, normal", [
    ("Ashirwad Paper Suppliers", "ASHIRWAD PAPER SUPPLIERS"),
    ("M/S ASHIRWAD PAPER SUPPLIERS PVT. LTD.", "ASHIRWAD PAPER SUPPLIERS"),
    ("m/s. Prime-Chem Industries Private Limited", "PRIME CHEM INDUSTRIES"),
    ("MS KAVERI TRADERS", "KAVERI TRADERS"),
    ("  City   Electricity Board, ", "CITY ELECTRICITY BOARD"),
    ("ITEMS/SUPPLY CO", "ITEMS SUPPLY CO"),  # only a whole M/S is dropped
    (None, ""), ("", ""),
])
def test_names_are_normalised_as_the_tdd_says(raw, normal):
    assert normalise_name(raw) == normal


@pytest.mark.parametrize("seen, names, ok", [
    ("ASHIRWAD PAPER SUPPLIERS", ["Ashirwad Paper Suppliers"], True),
    ("NEFT-ASHIRWAD PAPER SUPPLIERS PVT LTD-N2862", ["Ashirwad Paper Suppliers"], True),  # contains
    ("ASHIRWAD PAPERS", ["Ashirwad Paper Suppliers"], False),
    ("ASHIRWAD", ["Ashirwad Paper Suppliers"], False),  # the alert must contain the whole name
    ("A P S", ["Ashirwad Paper Suppliers", "A P S"], True),  # an alias the owner confirmed
    ("PAPER", ["Paper"], True),
    ("NEWSPAPER MART", ["Paper"], False),  # whole words only
    (None, ["Ashirwad Paper Suppliers"], False),
    ("ASHIRWAD PAPER SUPPLIERS", [], False),
])
def test_a_name_matches_when_it_equals_or_contains_the_vendor_name_or_an_alias(seen, names, ok):
    assert name_matches(seen, names) is ok


# --- AC1: one bill with a matching name -------------------------------------------------


def test_an_approved_payment_and_its_debit_become_paid_and_matched(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS", "N286261234567")
    result = _debit(env, t)
    assert result.replan is True and result.case_ids == []
    assert status(env, "payable", PAPER) == "PAID"
    assert status(env, "bank_txn", t) == "MATCHED"
    row = env.conn.execute("SELECT matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert row[0] == t
    assert env.conn.execute("SELECT party_id FROM bank_txn WHERE id = ?", (t,)).fetchone()[0] == 1
    events = env.conn.execute(
        "SELECT event_type, actor, source_ref FROM event WHERE event_type IN ('PAYABLE_PAID', 'BANK_TXN_MATCHED')"
    ).fetchall()
    assert sorted(tuple(e) for e in events) == [
        ("BANK_TXN_MATCHED", "reconciler", f"payable:{PAPER}"),
        ("PAYABLE_PAID", "reconciler", f"bank_txn:{t}"),
    ]


@pytest.mark.parametrize("day", [OCT(9), OCT(15)])
def test_the_debit_may_be_three_days_either_side_of_the_planned_date(env, day):
    plan_and_approve(env, PAPER)  # planned Mon 12 Oct
    assert _debit(env, txn(env, "debit", 18_000_000, day, "ASHIRWAD PAPER SUPPLIERS")).replan
    assert status(env, "payable", PAPER) == "PAID"


# The match and its bill moving together is driven through the real job handler in
# tests/test_reconcile_jobs.py (the review found a test here that supplied its own transaction).


# --- AC3: ambiguous and unknown debits ---------------------------------------------------


def test_one_bill_without_a_name_match_goes_to_review_with_a_case(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "SOMEONE ELSE ENTERPRISES")
    result = _debit(env, t)
    assert status(env, "payable", PAPER) == "REVIEW"
    assert status(env, "bank_txn", t) == "UNMATCHED"
    (case,) = cases(env)
    assert (case["kind"], case["subject_ref"], case["stake_paise"], case["status"]) == (
        "ambiguous_match", f"bank_txn:{t}", 18_000_000, "OPEN",
    )
    assert result.case_ids == [case["id"]]


def test_several_bills_with_a_matching_name_all_go_to_review_in_one_case(env):
    # Electricity made to look like a second ₹1,80,000 bill from the same payee,
    # planned Thu 15; the paper bill is planned Mon 12. Safety 0 so both are paid.
    env.conn.execute("UPDATE party SET name = 'Ashirwad Paper Suppliers' WHERE id = 2")
    env.conn.execute("UPDATE payable SET amount_paise = 18000000 WHERE id = ?", (ELEC,))
    env.conn.execute("UPDATE business SET safety_amount_paise = 0 WHERE id = 1")
    env.conn.commit()
    plan_and_approve(env, PAPER, ELEC)
    t = txn(env, "debit", 18_000_000, OCT(13), "ASHIRWAD PAPER SUPPLIERS")
    _debit(env, t)
    assert (status(env, "payable", PAPER), status(env, "payable", ELEC)) == ("REVIEW", "REVIEW")
    (case,) = cases(env)
    assert case["kind"] == "ambiguous_match"
    assert f"Candidate bill {PAPER}" in case["case_file_md"] and f"Candidate bill {ELEC}" in case["case_file_md"]


def test_a_debit_matching_no_bill_stays_unmatched_with_an_unknown_txn_case(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 1_234_500, OCT(12), "ASHIRWAD PAPER SUPPLIERS")
    result = _debit(env, t)
    assert result.replan is True  # the debit lowers the cash the next plan starts from
    assert status(env, "bank_txn", t) == "UNMATCHED"
    assert status(env, "payable", PAPER) == "PAYMENT_EXPECTED"
    (case,) = cases(env)
    assert (case["kind"], case["thinking"]) == ("unknown_txn", "medium")  # ₹12,345 is under ₹50,000


def test_a_planned_but_unapproved_bill_is_not_a_candidate(env):
    plan_and_approve(env)  # PLANNED, never approved
    _debit(env, txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS"))
    assert status(env, "payable", PAPER) == "PLANNED"
    assert cases(env)[0]["kind"] == "unknown_txn"


def test_a_debit_outside_the_window_is_not_a_candidate(env):
    plan_and_approve(env, PAPER)
    _debit(env, txn(env, "debit", 18_000_000, OCT(16), "ASHIRWAD PAPER SUPPLIERS"))
    assert status(env, "payable", PAPER) == "PAYMENT_EXPECTED"


def test_cases_above_the_escalation_amount_start_at_high_thinking(env):
    t = txn(env, "debit", 5_000_100, OCT(12), "UNKNOWN")  # ₹50,001 against a ₹50,000 escalation amount
    _debit(env, t)
    t2 = txn(env, "debit", 5_000_000, OCT(12), "UNKNOWN")  # exactly ₹50,000: not above it
    _debit(env, t2)
    assert [c["thinking"] for c in cases(env)] == ["high", "medium"]


def test_the_case_file_has_the_five_parts_with_code_filled_facts(env):
    t = txn(env, "debit", 1_234_500, OCT(12), "MYSTERY CO", "UTR99")
    _debit(env, t)
    md = cases(env)[0]["case_file_md"]
    for heading in ("## Goal", "## Facts", "## Findings", "## Unknowns", "## Notes"):
        assert heading in md
    assert "Debit of ₹12,345 on 2026-10-12 in account XXXX4821" in md
    assert "Counterparty as written: MYSTERY CO; reference: UTR99" in md


def test_a_malformed_alias_list_does_not_block_matching_on_the_name(env):
    env.conn.execute("UPDATE party SET aliases_json = 'not json' WHERE id = 1")
    env.conn.commit()
    plan_and_approve(env, PAPER)
    _debit(env, txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS"))
    assert status(env, "payable", PAPER) == "PAID"


def test_an_already_matched_debit_is_left_alone(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS")
    _debit(env, t)
    again = _debit(env, t)
    assert "nothing to match" in again.outcome and not again.replan
    assert len(cases(env)) == 0


# --- AC4: credits --------------------------------------------------------------------


def test_a_credit_matching_an_open_receivable_confirms_it(env):
    t = txn(env, "credit", 3_300_000, OCT(13), "KAVERI TRADERS", "N287265551210")
    result = _credit(env, t)
    assert result.replan
    assert status(env, "receivable", KAVERI) == "CONFIRMED"
    assert status(env, "bank_txn", t) == "MATCHED"
    rx = env.conn.execute("SELECT matched_txn_id FROM receivable WHERE id = ?", (KAVERI,)).fetchone()
    assert rx[0] == t


def test_a_credit_from_a_known_payer_with_a_different_amount_opens_a_case(env):
    t = txn(env, "credit", 1_000_000, OCT(13), "NANDI FOODS")  # Nandi owes ₹2,00,000
    result = _credit(env, t)
    assert status(env, "receivable", NANDI) == "EXPECTED"
    assert status(env, "bank_txn", t) == "UNMATCHED"
    (case,) = cases(env)
    assert case["kind"] == "ambiguous_match" and result.case_ids == [case["id"]]
    assert "Receivable 2 from the same payer: ₹2,00,000" in case["case_file_md"]


def test_a_credit_from_nobody_known_is_an_unknown_txn(env):
    _credit(env, txn(env, "credit", 1_000_000, OCT(13), "RANDOM PERSON"))
    assert cases(env)[0]["kind"] == "unknown_txn"


def test_an_expected_receivable_paid_early_inside_the_window_matches(env):
    # Nandi is expected Wed 28 Oct; a credit on Mon 26 is inside 3 days
    t = txn(env, "credit", 20_000_000, OCT(26), "NANDI FOODS PVT LTD")
    _credit(env, t)
    assert status(env, "receivable", NANDI) == "CONFIRMED"


def test_payment_expected_without_a_planned_date_is_never_matched(env):
    plan_and_approve(env, PAPER)
    env.conn.execute("UPDATE payable SET planned_date = NULL WHERE id = ?", (PAPER,))
    env.conn.commit()
    _debit(env, txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS"))
    assert status(env, "payable", PAPER) == "PAYMENT_EXPECTED"
    assert cases(env)[0]["kind"] == "unknown_txn"


def test_a_credit_outside_the_expected_date_window_is_a_case(env):
    t = txn(env, "credit", 3_300_000, OCT(17), "KAVERI TRADERS")  # Kaveri expected Tue 13: 4 days off
    _credit(env, t)
    assert status(env, "receivable", KAVERI) == "COMMITTED"
    assert cases(env)[0]["kind"] == "ambiguous_match"


# --- D13: the date the owner asked a customer to pay by ---------------------------------


def _choose_nandi_early(env, chosen=True):
    from app.jobs.replan import replan
    from app.ledger import writer

    replan(env.conn, 1, triggered_by="test", clock=env.clock)
    option_id = env.conn.execute("SELECT id FROM shortfall_option WHERE kind = 'early_receipt'").fetchone()[0]
    if chosen:
        writer.choose_option(option_id, "owner:1", "ask Nandi to pay by Fri 16", None, conn=env.conn, clock=env.clock)


def test_a_credit_near_the_date_the_owner_asked_for_matches_the_receivable(env):
    _choose_nandi_early(env)  # Nandi expected Wed 28 Oct; asked to pay by Fri 16 Oct
    result = _credit(env, txn(env, "credit", 20_000_000, OCT(16), "NANDI FOODS"))
    assert result.outcome == f"matched receivable {NANDI}: CONFIRMED"
    assert status(env, "receivable", NANDI) == "CONFIRMED" and cases(env) == []


def test_an_early_receipt_option_that_was_not_chosen_does_not_widen_the_window(env):
    _choose_nandi_early(env, chosen=False)
    _credit(env, txn(env, "credit", 20_000_000, OCT(16), "NANDI FOODS"))
    assert status(env, "receivable", NANDI) == "EXPECTED"
    assert cases(env)[0]["kind"] == "ambiguous_match"


def test_the_asked_date_still_needs_the_name_and_the_amount(env):
    _choose_nandi_early(env)
    _credit(env, txn(env, "credit", 19_000_000, OCT(16), "NANDI FOODS"))
    _credit(env, txn(env, "credit", 20_000_000, OCT(16), "SOMEONE ELSE"))
    assert status(env, "receivable", NANDI) == "EXPECTED"
