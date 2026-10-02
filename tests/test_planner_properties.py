"""Part 1's planner invariants on random snapshots (CHG-003 AC2, I1-I7)."""

from dataclasses import replace
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.planner.forecast import opening_cash, project
from app.planner.options import options
from app.planner.plan import (
    AccountCash,
    CommitmentIn,
    InflowIn,
    PayableIn,
    PlanSnapshot,
    canonical_json,
    plan,
)

PAISE = st.integers(min_value=1, max_value=10**9)


@st.composite
def snapshots(draw):
    today = draw(st.dates(min_value=date(2026, 1, 1), max_value=date(2027, 12, 31)))
    horizon_days = draw(st.integers(min_value=1, max_value=21))
    # Mostly inside the horizon, with overdue and after-horizon dates mixed in.
    near = st.integers(min_value=-5, max_value=horizon_days + 5).map(
        lambda n: today + timedelta(days=n)
    )

    accounts = tuple(
        AccountCash(i, draw(st.integers(-10**8, 10**9)), draw(st.none() | st.integers(-10**8, 10**9)),
                    draw(st.booleans()))
        for i in range(1, draw(st.integers(0, 3)) + 1)
    )
    payables = []
    for i in range(1, draw(st.integers(0, 8)) + 1):
        amount = draw(PAISE)
        status = draw(st.sampled_from(["CONFIRMED", "PLANNED", "REOPENED", "PAYMENT_EXPECTED"]))
        discount = draw(st.none() | st.integers(1, max(1, amount - 1))) if amount > 1 else None
        payables.append(PayableIn(
            payable_id=i,
            amount_paise=amount,
            due_date=draw(near),
            priority=draw(st.sampled_from(["statutory", "critical", "normal", "flexible"])),
            grace_days=draw(st.integers(0, 10)),
            discount_paise=discount,
            discount_by=draw(near) if discount else None,
            status=status,
            planned_date=draw(st.none() | near) if status in ("PLANNED", "PAYMENT_EXPECTED") else None,
        ))
    horizon_end = today + timedelta(days=horizon_days - 1)
    inside = st.integers(0, horizon_days - 1).map(lambda n: today + timedelta(days=n))
    inflows = tuple(
        InflowIn(i, draw(PAISE), draw(inside), "COMMITTED") for i in range(1, draw(st.integers(0, 3)) + 1)
    )
    later = st.integers(min_value=7, max_value=horizon_days + 20).map(
        lambda n: today + timedelta(days=n)
    )
    uncounted = tuple(
        InflowIn(100 + i, draw(PAISE), draw(later), "EXPECTED")
        for i in range(1, draw(st.integers(0, 2)) + 1)
    ) + tuple(
        InflowIn(200 + i, draw(PAISE), horizon_end + timedelta(days=draw(st.integers(1, 20))), "COMMITTED")
        for i in range(1, draw(st.integers(0, 1)) + 1)
    )
    commitments = tuple(
        CommitmentIn(i, draw(near), draw(PAISE), "fixed") for i in range(1, draw(st.integers(0, 2)) + 1)
    )
    return PlanSnapshot(
        today=today,
        horizon_days=horizon_days,
        # Empty payment days is a real (if odd) setting, but only one draw in ten.
        payment_days=frozenset() if draw(st.integers(0, 9)) == 0
        else draw(st.frozensets(st.integers(0, 6), min_size=1)),
        safety_paise=draw(st.integers(0, max(0, opening_cash(accounts)))),
        accounts=accounts,
        payables=tuple(payables),
        inflows=inflows,
        commitments=commitments,
        uncounted_inflows=uncounted,
    )


def _horizon(s):
    return [s.today + timedelta(days=i) for i in range(s.horizon_days)]


def _normal_target_day(s, p):
    """Independent restatement of the target rule: latest payment day in
    [today, due], else the next payment day on or after today."""
    d = p.due_date
    while d >= s.today:
        if d.weekday() in s.payment_days:
            return d
        d -= timedelta(days=1)
    for i in range(7):
        d = s.today + timedelta(days=i)
        if d.weekday() in s.payment_days:
            return d
    return None


@settings(max_examples=200, deadline=None)
@given(snapshots())
def test_i1_paying_the_pay_lines_never_takes_a_paid_day_below_safety(s):
    # Rebuild the curve from the base movements plus only the PAY bills. Every
    # non-statutory PAY was placed because the days from its pay date on stayed
    # at or above safety, so that must hold on the final curve. (Escalated bills
    # are left out: they are not being paid.)
    r = plan(s)
    pay = {line.payable_id for line in r.lines if line.decision == "PAY"}
    paid_curve = project(
        r.opening_cash_paise,
        [m for m in r.movements if m.source != "bill" or m.ref_id in pay],
        _horizon(s),
    )
    statutory = {p.payable_id for p in s.payables if p.priority == "statutory"}
    for line in r.lines:
        if line.decision == "PAY" and line.payable_id not in statutory:
            assert all(b.balance_paise >= s.safety_paise for b in paid_curve if b.day >= line.pay_on)
    if r.valid:
        assert all(b.balance_paise >= s.safety_paise for b in r.days)


@settings(max_examples=200, deadline=None)
@given(snapshots())
def test_i2_every_rupee_in_the_forecast_traces_to_a_snapshot_record(s):
    r = plan(s)
    for b in r.days:
        assert b.balance_paise == r.opening_cash_paise + sum(
            m.amount_paise for m in r.movements if m.day <= b.day
        )
    inflows = {i.receivable_id: i for i in s.inflows}
    commitments = {c.commitment_id: c for c in s.commitments}
    payables = {p.payable_id: p for p in s.payables}
    days = set(_horizon(s))
    for m in r.movements:
        assert m.day in days
        if m.source == "inflow":
            assert m.amount_paise == inflows[m.ref_id].amount_paise
        elif m.source == "commitment":
            assert m.amount_paise == -commitments[m.ref_id].amount_paise
        else:
            p = payables[m.ref_id]
            allowed = {p.amount_paise} | ({p.amount_paise - p.discount_paise} if p.discount_paise else set())
            assert -m.amount_paise in allowed
            assert (m.source == "payment_expected") == (p.status == "PAYMENT_EXPECTED")

    # Complete and never counted twice.
    keys = [(m.source, m.ref_id) for m in r.movements]
    assert len(keys) == len(set(keys))
    first, last = s.today, s.today + timedelta(days=s.horizon_days - 1)
    refs = {src: {m.ref_id for m in r.movements if m.source == src}
            for src in ("inflow", "commitment", "payment_expected", "bill")}
    assert refs["inflow"] == {i.receivable_id for i in s.inflows if first <= i.expected_date <= last}
    assert refs["commitment"] == {c.commitment_id for c in s.commitments if first <= c.day <= last}
    assert refs["payment_expected"] == {
        p.payable_id for p in s.payables
        if p.status == "PAYMENT_EXPECTED" and max(p.planned_date or first, first) <= last
    }
    assert refs["bill"] == {line.payable_id for line in r.lines if line.decision != "WAIT"}
    bill_moves = {m.ref_id: m for m in r.movements if m.source == "bill"}
    for line in r.lines:
        if line.decision == "PAY":
            m = bill_moves[line.payable_id]
            assert (m.day, -m.amount_paise) == (line.pay_on, line.amount_paise)


@settings(max_examples=200, deadline=None)
@given(snapshots(), st.data())
def test_i3_unresolved_drift_uses_the_lower_balance(s, data):
    expected = sum(
        min(a.calculated_paise, a.reported_paise)
        if a.drift_unresolved and a.reported_paise is not None else a.calculated_paise
        for a in s.accounts
    )
    assert plan(s).opening_cash_paise == expected
    drifted = [a for a in s.accounts if a.drift_unresolved and a.reported_paise is not None]
    if drifted:
        a = data.draw(st.sampled_from(drifted))
        lower = replace(a, reported_paise=a.reported_paise - data.draw(st.integers(1, 10**6)))
        accounts = tuple(lower if x is a else x for x in s.accounts)
        assert opening_cash(accounts) <= opening_cash(s.accounts)


@settings(max_examples=200, deadline=None)
@given(snapshots())
def test_i4_statutory_never_escalates_and_pay_dates_are_payment_days_in_the_horizon(s):
    r = plan(s)
    horizon_end = s.today + timedelta(days=s.horizon_days - 1)
    payables = {p.payable_id: p for p in s.payables}
    for line in r.lines:
        p = payables[line.payable_id]
        if p.priority == "statutory":
            assert line.decision != "ESCALATE"
        if line.decision == "PAY":
            assert line.pay_on.weekday() in s.payment_days
            assert s.today <= line.pay_on <= horizon_end
        target = _normal_target_day(s, p)
        target_in_horizon = target is not None and target <= horizon_end
        if target_in_horizon:
            assert line.decision != "WAIT"
        elif line.decision != "WAIT":
            # Only a discount day inside the horizon can plan a bill whose normal
            # target is outside it, and then at the discounted amount.
            assert line.decision == "PAY" and p.discount_paise
            assert line.amount_paise == p.amount_paise - p.discount_paise
        if line.decision == "ESCALATE":
            assert "below the safety amount from" in line.reason


@settings(max_examples=200, deadline=None)
@given(snapshots())
def test_i5_one_line_per_plannable_bill_and_none_for_payment_expected(s):
    r = plan(s)
    plannable = sorted(p.payable_id for p in s.payables if p.status != "PAYMENT_EXPECTED")
    assert [line.payable_id for line in r.lines] == plannable


@settings(max_examples=100, deadline=None)
@given(snapshots())
def test_i6_each_option_meets_the_rule_exactly_when_its_rerun_is_valid(s):
    r = plan(s)
    opts = options(s, r)
    assert (opts == []) == r.valid
    for o in opts:
        if o.plan is not None:
            assert o.meets_rule == o.plan.valid
            assert o.lowest_balance_paise == o.plan.lowest_balance_paise
        else:
            assert o.meets_rule is False


@settings(max_examples=200, deadline=None)
@given(snapshots())
def test_i7_amounts_are_ints_and_plan_is_deterministic(s):
    r = plan(s)
    for value in (r.opening_cash_paise, r.lowest_balance_paise, r.gap_paise):
        assert type(value) is int
    for b in r.days:
        assert type(b.balance_paise) is int
    for line in r.lines:
        assert type(line.amount_paise) is int
    for m in r.movements:
        assert type(m.amount_paise) is int
    assert canonical_json(r) == canonical_json(plan(s))
