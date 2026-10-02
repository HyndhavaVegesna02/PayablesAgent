"""TDD Part 1 "Worked example" as the planner's golden test."""

from datetime import timedelta

from app.planner.plan import PlanLine, plan
from tests.planner_fixtures import ORIGINAL_PLAN, TODAY, oct, worked_example


def test_every_daily_balance_matches_part1():
    r = plan(worked_example())
    assert [b.day for b in r.days] == [TODAY + timedelta(days=i) for i in range(14)]
    assert [b.balance_paise for b in r.days] == ORIGINAL_PLAN


def test_lowest_balance_breach_and_gap():
    r = plan(worked_example())
    assert r.opening_cash_paise == 62_000_000
    assert (r.lowest_balance_paise, r.lowest_on) == (18_300_000, oct(22))  # ₹1,83,000 on Thu 22 Oct
    assert r.breach_on == oct(22)
    assert r.gap_paise == 6_700_000  # ₹67,000 below
    assert r.valid is False


def test_four_earlier_payments_pay_and_prime_chem_escalates():
    r = plan(worked_example())
    assert r.lines == (
        PlanLine(1, "PAY", oct(12), 18_000_000,
                 "Pay ₹1,80,000 on Mon 12 Oct: latest payment day on or before the due date (Wed 14 Oct)."),
        PlanLine(2, "PAY", oct(15), 4_500_000,
                 "Pay ₹45,000 on Thu 15 Oct: latest payment day on or before the due date (Thu 15 Oct)."),
        PlanLine(3, "PAY", oct(15), 3_500_000,
                 "Pay ₹35,000 on Thu 15 Oct: latest payment day on or before the due date (Fri 16 Oct)."),
        PlanLine(4, "PAY", oct(19), 9_000_000,
                 "Pay ₹90,000 on Mon 19 Oct: latest payment day on or before the due date (Tue 20 Oct)."),
        PlanLine(5, "ESCALATE", None, 12_000_000,
                 "Paying ₹1,20,000 on Thu 22 Oct takes the balance below the safety amount from "
                 "Thu 22 Oct: lowest ₹1,83,000 on Thu 22 Oct, ₹67,000 below."),
    )
    assert [(e.payable_id, e.breach_on, e.gap_paise) for e in r.escalations] == [(5, oct(22), 6_700_000)]

