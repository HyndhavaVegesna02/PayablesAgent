from datetime import date

from app.planner.options import options
from app.planner.plan import AccountCash, InflowIn, PayableIn, plan
from tests.planner_fixtures import NANDI_PAYS_FRI_16, oct, snapshot, worked_example


def _opts(s):
    return options(s, plan(s))


# --- the worked example: exactly Part 1's three options -------------------------


def test_worked_example_gives_exactly_the_three_part1_options():
    got = [(o.kind, o.params, o.lowest_balance_paise, o.lowest_on, o.meets_rule)
           for o in _opts(worked_example())]
    assert got == [
        ("early_receipt",
         {"receivable_id": 2, "amount_paise": 20_000_000, "from_date": "2026-10-28",
          "to_date": "2026-10-16"},
         38_300_000, oct(22), True),                     # ₹3,83,000 on 22 Oct: yes
        ("split",
         {"payable_id": 5, "pay_now_paise": 5_300_000, "rest_paise": 6_700_000,
          "rest_due": "2026-10-26"},
         25_000_000, oct(22), True),                     # ₹2,50,000 on 22 Oct: yes, exactly
        ("authorise_breach", {"gap_paise": 6_700_000, "lowest_on": "2026-10-22"},
         18_300_000, oct(22), False),                    # ₹1,83,000: no, ₹67,000 below
    ]


def test_nandi_pays_on_fri_16_reproduces_part1s_second_column():
    early = _opts(worked_example())[0]
    assert early.params["to_date"] == "2026-10-16"  # D6: Thu 22 -> Mon 19 -> Fri 16
    assert [b.balance_paise for b in early.plan.days] == NANDI_PAYS_FRI_16
    prime = next(line for line in early.plan.lines if line.payable_id == 5)
    assert (prime.decision, prime.pay_on) == ("PAY", oct(22))


def test_split_pays_53000_now_and_waits_the_rest():
    split = _opts(worked_example())[1]
    lines = {line.payable_id: line for line in split.plan.lines}
    assert (lines[5].decision, lines[5].pay_on, lines[5].amount_paise) == ("PAY", oct(22), 5_300_000)
    assert (lines[-5].decision, lines[-5].amount_paise) == ("WAIT", 6_700_000)


def test_a_valid_plan_has_no_options():
    assert _opts(snapshot(payables=(PayableIn(1, 100, oct(14), "normal"),))) == []


# --- D6 edge: never ask for money in the past -----------------------------------


def test_early_receipt_not_offered_when_the_ask_by_day_is_already_past():
    # Breach on Thu 15 -> payment day Mon 12 (today) -> weekday before it is Fri 9: in the past.
    s = snapshot(
        accounts=(AccountCash(1, 10_000, None, False),), safety_paise=5_000,
        payables=(PayableIn(1, 6_000, oct(15), "normal"),),
        uncounted_inflows=(InflowIn(9, 50_000, oct(28), "EXPECTED"),),
    )
    r = plan(s)
    assert r.breach_on == oct(15)
    assert [o.kind for o in options(s, r)] == ["split", "authorise_breach"]


def test_early_receipt_offered_for_a_committed_inflow_dated_after_the_breach():
    s = snapshot(
        accounts=(AccountCash(1, 10_000, None, False),), safety_paise=5_000,
        payables=(PayableIn(1, 6_000, oct(22), "normal"),),
        inflows=(InflowIn(3, 4_000, oct(23), "COMMITTED"),),
    )
    early = [o for o in _opts(s) if o.kind == "early_receipt"]
    assert [o.params["to_date"] for o in early] == ["2026-10-16"]
    assert early[0].meets_rule is True


# --- the other option kinds -----------------------------------------------------


def test_delay_flexible_moves_to_the_latest_payment_day_within_grace():
    s = snapshot(
        accounts=(AccountCash(1, 10_000, None, False),), safety_paise=5_000,
        payables=(PayableIn(1, 6_000, oct(15), "flexible", grace_days=7),),
        inflows=(InflowIn(3, 4_000, oct(20), "COMMITTED"),),
    )
    delay = next(o for o in _opts(s) if o.kind == "delay_flexible")
    assert delay.params == {"payable_id": 1, "from_date": "2026-10-15", "to_date": "2026-10-22"}
    assert delay.meets_rule is True


def test_delay_flexible_names_the_payment_day_even_after_the_horizon():
    s = snapshot(
        accounts=(AccountCash(1, 10_000, None, False),), safety_paise=5_000,
        payables=(PayableIn(1, 6_000, oct(22), "flexible", grace_days=7),),
    )
    delay = next(o for o in _opts(s) if o.kind == "delay_flexible")
    assert delay.params["to_date"] == "2026-10-29"  # Thu 29 Oct, after the horizon
    line = next(x for x in delay.plan.lines if x.payable_id == 1)
    assert line.decision == "WAIT"


def test_ask_ca_when_statutory_bills_alone_breach():
    s = snapshot(
        accounts=(AccountCash(1, 10_000, None, False),), safety_paise=5_000,
        payables=(PayableIn(1, 6_000, oct(15), "statutory"),),
    )
    kinds = [o.kind for o in _opts(s)]
    assert kinds == ["authorise_breach", "ask_ca"]
    ask = _opts(s)[-1]
    assert (ask.lowest_balance_paise, ask.meets_rule, ask.plan) == (None, False, None)


def test_no_split_when_the_gap_is_the_whole_bill():
    s = snapshot(accounts=(AccountCash(1, 100, None, False),), safety_paise=200,
                 payables=(PayableIn(1, 50, date(2026, 10, 15), "normal"),))
    assert "split" not in [o.kind for o in _opts(s)]


def test_delay_flexible_rerun_applies_the_delay_it_names_and_drops_the_discount():
    s = snapshot(
        accounts=(AccountCash(1, 100_000, None, False),), safety_paise=50_000,
        payables=(
            PayableIn(1, 10_000, oct(19), "flexible", grace_days=7,
                      discount_paise=1_000, discount_by=oct(12)),
            PayableIn(2, 60_000, oct(22), "normal"),
        ),
    )
    r = plan(s)
    assert next(x for x in r.lines if x.payable_id == 1).pay_on == oct(12)  # paid early, discounted
    delay = next(o for o in _opts(s) if o.kind == "delay_flexible")
    assert delay.params == {"payable_id": 1, "from_date": "2026-10-12", "to_date": "2026-10-26"}
    line = next(x for x in delay.plan.lines if x.payable_id == 1)
    assert (line.decision, line.amount_paise) == ("WAIT", 10_000)  # 26 Oct is after the horizon


def test_delay_flexible_not_offered_when_grace_reaches_no_later_payment_day():
    # Due Mon 12 with 2 grace days: the latest payment day by Wed 14 is still Mon 12.
    s = snapshot(
        accounts=(AccountCash(1, 10_000, None, False),), safety_paise=5_000,
        payables=(PayableIn(1, 6_000, oct(12), "flexible", grace_days=2),),
    )
    assert "delay_flexible" not in [o.kind for o in _opts(s)]
