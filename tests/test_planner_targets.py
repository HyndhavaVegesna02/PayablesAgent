"""Target-day, base-curve and validity rules the TDD leaves implicit, each
pinned by the batch 1 plan (CHG-003 "Algorithm") and PO decision D9."""

from datetime import date

from app.planner.plan import AccountCash, CommitmentIn, InflowIn, PayableIn, plan
from tests.planner_fixtures import oct, snapshot


def _line(r, pid):
    return next(line for line in r.lines if line.payable_id == pid)


def _cash(paise):
    return (AccountCash(1, paise, None, False),)


# --- target day -----------------------------------------------------------------


def test_never_targets_a_day_before_today():
    # Tue 13: no payment day in [Tue 13, Wed 14], so the next one (Thu 15) is used.
    r = plan(snapshot(today=oct(13), payables=(PayableIn(1, 100, oct(14), "normal"),)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on) == ("PAY", oct(15))
    assert line.reason == (
        "Pay ₹1 on Thu 15 Oct: no payment day between today and the due date (Wed 14 Oct); "
        "next payment day."
    )


def test_overdue_bill_targets_today_when_today_is_a_payment_day():
    r = plan(snapshot(today=oct(12), payables=(PayableIn(1, 100, oct(9), "normal"),)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on) == ("PAY", oct(12))
    assert line.reason == "Pay ₹1 on Mon 12 Oct: overdue since Fri 9 Oct; next payment day."


def test_overdue_bill_on_a_non_payment_day_targets_the_next_one():
    r = plan(snapshot(today=oct(13), payables=(PayableIn(1, 100, oct(9), "normal"),)))
    assert _line(r, 1).pay_on == oct(15)


def test_bill_due_after_the_horizon_waits():
    r = plan(snapshot(payables=(PayableIn(1, 100, oct(26), "normal"),)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on) == ("WAIT", None)
    assert line.reason == "Wait: due Mon 26 Oct, after the planning horizon (ends Sun 25 Oct)."
    assert r.movements == ()


def test_a_bill_due_after_the_horizon_pays_if_its_payment_day_is_inside_it():
    # Payment day Thursday only: the latest one before Tue 27 Oct is Thu 22, inside the horizon.
    r = plan(snapshot(payment_days=frozenset({3}), payables=(PayableIn(1, 100, oct(27), "normal"),)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on) == ("PAY", oct(22))
    assert line.reason == "Pay ₹1 on Thu 22 Oct: latest payment day on or before the due date (Tue 27 Oct)."


def test_no_payment_days_means_everything_waits():
    r = plan(snapshot(payment_days=frozenset(), payables=(PayableIn(1, 100, oct(14), "statutory"),)))
    line = _line(r, 1)
    assert line.decision == "WAIT"
    assert line.reason == "Wait: no payment day in the planning horizon (ends Sun 25 Oct)."


def test_no_payment_day_inside_a_short_horizon_waits():
    r = plan(snapshot(today=oct(13), horizon_days=1, payables=(PayableIn(1, 100, oct(13), "normal"),)))
    assert _line(r, 1).decision == "WAIT"


def test_planned_bills_are_retargeted_from_scratch():
    p = PayableIn(1, 100, oct(22), "normal", status="PLANNED", planned_date=oct(15))
    assert _line(plan(snapshot(payables=(p,))), 1).pay_on == oct(22)


# --- base curve -------------------------------------------------------------------


def test_payment_expected_is_subtracted_on_its_planned_day_and_gets_no_line():
    p = PayableIn(1, 1_000, oct(16), "normal", status="PAYMENT_EXPECTED", planned_date=oct(15))
    r = plan(snapshot(accounts=_cash(10_000), payables=(p,)))
    assert r.lines == ()
    bal = {b.day: b.balance_paise for b in r.days}
    assert (bal[oct(14)], bal[oct(15)]) == (10_000, 9_000)


def test_payment_expected_in_the_past_or_undated_is_subtracted_today():
    for planned in (oct(8), None):
        p = PayableIn(1, 1_000, oct(9), "normal", status="PAYMENT_EXPECTED", planned_date=planned)
        r = plan(snapshot(accounts=_cash(10_000), payables=(p,)))
        assert r.days[0].balance_paise == 9_000


def test_payment_expected_after_the_horizon_is_not_counted():
    p = PayableIn(1, 1_000, oct(30), "normal", status="PAYMENT_EXPECTED", planned_date=oct(29))
    r = plan(snapshot(accounts=_cash(10_000), payables=(p,)))
    assert {b.balance_paise for b in r.days} == {10_000}


def test_inflows_outside_the_horizon_are_ignored():
    inflows = (InflowIn(1, 500, oct(11), "COMMITTED"), InflowIn(2, 700, oct(26), "COMMITTED"))
    r = plan(snapshot(accounts=_cash(10_000), inflows=inflows))
    assert {b.balance_paise for b in r.days} == {10_000}


def test_commitments_are_subtracted_in_the_base_curve():
    r = plan(snapshot(accounts=_cash(10_000), commitments=(CommitmentIn(1, oct(14), 2_500, "rent"),)))
    bal = {b.day: b.balance_paise for b in r.days}
    assert (bal[oct(13)], bal[oct(14)], bal[oct(25)]) == (10_000, 7_500, 7_500)


# --- placement and validity ---------------------------------------------------------


def test_statutory_is_placed_first_and_always_paid():
    payables = (
        PayableIn(1, 6_000, oct(12), "normal"),     # due earlier, but placed after statutory
        PayableIn(2, 6_000, oct(15), "statutory"),
    )
    r = plan(snapshot(accounts=_cash(10_000), safety_paise=3_000, payables=payables))
    assert (_line(r, 1).decision, _line(r, 2).decision) == ("ESCALATE", "PAY")


def test_a_statutory_breach_still_pays_and_makes_the_plan_invalid():
    r = plan(snapshot(accounts=_cash(10_000), safety_paise=5_000,
                      payables=(PayableIn(1, 6_000, oct(15), "statutory"),)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on) == ("PAY", oct(15))
    assert line.reason == (
        "Pay ₹60 on Thu 15 Oct: statutory, paid on time although it takes the balance below the "
        "safety amount from Thu 15 Oct: lowest ₹40 on Thu 15 Oct, ₹10 below."
    )
    assert r.escalations == ()
    assert (r.valid, r.breach_on, r.gap_paise) == (False, oct(15), 1_000)


def test_a_base_curve_already_below_safety_is_invalid_with_no_bills():
    r = plan(snapshot(accounts=_cash(100), safety_paise=200))
    assert (r.valid, r.breach_on, r.lowest_balance_paise, r.gap_paise) == (False, oct(12), 100, 100)


# --- D9: discounts ------------------------------------------------------------------


def _discounted(**over):
    base = dict(payable_id=1, amount_paise=12_000_000, due_date=oct(22), priority="normal",
                discount_paise=200_000, discount_by=oct(19))
    return PayableIn(**{**base, **over})


def test_discount_taken_when_paying_early_is_safe():
    r = plan(snapshot(accounts=_cash(100_000_000), safety_paise=25_000_000, payables=(_discounted(),)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on, line.amount_paise) == ("PAY", oct(19), 11_800_000)
    assert line.reason == "Pay ₹1,18,000 on Mon 19 Oct: by the discount date (Mon 19 Oct), saving ₹2,000."


def test_discount_skipped_falls_back_to_the_due_date_at_full_amount():
    # Early payment breaches; a receipt on Wed 21 makes the due-date payment safe.
    r = plan(snapshot(accounts=_cash(30_000_000), safety_paise=25_000_000, payables=(_discounted(),),
                      inflows=(InflowIn(1, 10_000_000, oct(21), "COMMITTED"),)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on, line.amount_paise) == ("PAY", oct(22), 12_000_000)
    assert line.reason == (
        "Pay ₹1,20,000 on Thu 22 Oct: latest payment day on or before the due date (Thu 22 Oct). "
        "Early-payment discount of ₹2,000 skipped: paying ₹1,18,000 on Mon 19 Oct would take the "
        "balance below the safety amount."
    )
    assert r.valid  # no false alarm: the bill is simply paid on time


def test_discount_skipped_and_due_date_also_breaches_escalates():
    r = plan(snapshot(accounts=_cash(30_000_000), safety_paise=25_000_000, payables=(_discounted(),)))
    line = _line(r, 1)
    assert (line.decision, line.amount_paise) == ("ESCALATE", 12_000_000)
    assert line.reason.startswith("Paying ₹1,20,000 on Thu 22 Oct takes the balance below the safety amount")
    assert line.reason.endswith(
        "Early-payment discount of ₹2,000 skipped: paying ₹1,18,000 on Mon 19 Oct would take the "
        "balance below the safety amount."
    )


def test_discount_on_a_bill_due_after_the_horizon_is_still_taken():
    p = _discounted(due_date=oct(30), discount_by=oct(15))
    line = _line(plan(snapshot(accounts=_cash(100_000_000), payables=(p,))), 1)
    assert (line.decision, line.pay_on, line.amount_paise) == ("PAY", oct(15), 11_800_000)


def test_unsafe_discount_on_a_bill_due_after_the_horizon_waits_and_says_why():
    p = _discounted(due_date=oct(30), discount_by=oct(15))
    r = plan(snapshot(accounts=_cash(30_000_000), safety_paise=25_000_000, payables=(p,)))
    line = _line(r, 1)
    assert (line.decision, line.pay_on) == ("WAIT", None)
    assert line.reason == (
        "Wait: due Fri 30 Oct, after the planning horizon (ends Sun 25 Oct). Early-payment "
        "discount of ₹2,000 skipped: paying ₹1,18,000 on Thu 15 Oct would take the balance "
        "below the safety amount."
    )


def test_escalation_reports_breach_day_and_gap_away_from_the_target_day():
    # Target Mon 12 fits that day; a commitment on Wed 14 breaches; the lowest day is Tue 20.
    s = snapshot(
        accounts=_cash(10_000), safety_paise=4_000,
        payables=(PayableIn(1, 5_000, oct(14), "normal"),),
        commitments=(CommitmentIn(1, oct(14), 2_000, "rent"), CommitmentIn(2, oct(20), 1_000, "wages")),
    )
    r = plan(s)
    (e,) = r.escalations
    assert (e.target_on, e.breach_on, e.lowest_on, e.lowest_paise, e.gap_paise) == (
        oct(12), oct(14), oct(20), 2_000, 2_000,
    )
    assert _line(r, 1).reason == (
        "Paying ₹50 on Mon 12 Oct takes the balance below the safety amount from Wed 14 Oct: "
        "lowest ₹20 on Tue 20 Oct, ₹20 below."
    )


def test_planner_refuses_a_horizon_shorter_than_one_day():
    import pytest

    with pytest.raises(ValueError):
        plan(snapshot(horizon_days=0))


def test_a_past_discount_date_is_ignored():
    r = plan(snapshot(payables=(_discounted(discount_by=date(2026, 10, 9)),)))
    assert (_line(r, 1).pay_on, _line(r, 1).amount_paise) == (oct(22), 12_000_000)
