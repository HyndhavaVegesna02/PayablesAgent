"""Shortfall options (TDD Part 2, "Planning engine", Shortfall options).

Each option with numbers is the same plan() run on a changed snapshot, so its
figures come from the same code as the plan. The owner chooses; nothing here
picks one."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Literal

from app.planner.plan import (
    InflowIn,
    PayableIn,
    PlanResult,
    PlanSnapshot,
    latest_payment_day,
    plan,
)

OptionKind = Literal["early_receipt", "split", "delay_flexible", "authorise_breach", "ask_ca"]


@dataclass(frozen=True)
class OptionResult:
    kind: OptionKind
    params: dict[str, Any] = field(hash=False)  # ints and ISO dates: ready for params_json
    lowest_balance_paise: int | None
    lowest_on: date | None
    meets_rule: bool
    plan: PlanResult | None  # the what-if run behind the numbers; None when there is none


def _last_before(d: date, ok) -> date:
    d -= timedelta(days=1)
    while not ok(d):
        d -= timedelta(days=1)
    return d


def _from_rerun(kind: OptionKind, params: dict[str, Any], r: PlanResult) -> OptionResult:
    return OptionResult(kind, params, r.lowest_balance_paise, r.lowest_on, r.valid, r)


def _early_receipts(s: PlanSnapshot, r: PlanResult) -> list[OptionResult]:
    if r.breach_on is None or not s.payment_days:
        return []
    # D6: the last weekday (Mon-Fri) strictly before the last payment day strictly
    # before the breach day. Worked example: Thu 22 -> Mon 19 -> Fri 16 Oct.
    pay_day = _last_before(r.breach_on, lambda d: d.weekday() in s.payment_days)
    ask_by = _last_before(pay_day, lambda d: d.weekday() < 5)
    if pay_day < s.today or ask_by < s.today:
        return []
    out = []
    candidates = sorted(s.inflows + s.uncounted_inflows, key=lambda i: i.receivable_id)
    for i in candidates:
        if i.expected_date <= r.breach_on:
            continue
        moved = InflowIn(i.receivable_id, i.amount_paise, ask_by, "COMMITTED")
        what_if = replace(
            s,
            inflows=tuple(x for x in s.inflows if x != i) + (moved,),
            uncounted_inflows=tuple(x for x in s.uncounted_inflows if x != i),
        )
        out.append(_from_rerun(
            "early_receipt",
            {"receivable_id": i.receivable_id, "amount_paise": i.amount_paise,
             "from_date": i.expected_date.isoformat(), "to_date": ask_by.isoformat()},
            plan(what_if),
        ))
    return out


def _splits(s: PlanSnapshot, r: PlanResult) -> list[OptionResult]:
    out = []
    by_id = {p.payable_id: p for p in s.payables}
    rest_due = r.horizon_end + timedelta(days=1)
    for e in r.escalations:
        p = by_id[e.payable_id]
        pay_now = p.amount_paise - e.gap_paise
        if pay_now <= 0:
            continue
        now_part = replace(p, amount_paise=pay_now, discount_paise=None, discount_by=None)
        # The rest becomes a child bill after the horizon, as split_payable would make it.
        # -id marks it as a what-if record: it must never be persisted as a plan line.
        rest_part = PayableIn(-p.payable_id, e.gap_paise, rest_due, p.priority,
                              grace_days=p.grace_days)
        what_if = replace(
            s, payables=tuple(x for x in s.payables if x is not p) + (now_part, rest_part)
        )
        out.append(_from_rerun(
            "split",
            {"payable_id": p.payable_id, "pay_now_paise": pay_now, "rest_paise": e.gap_paise,
             "rest_due": rest_due.isoformat()},
            plan(what_if),
        ))
    return out


def _delays(s: PlanSnapshot, r: PlanResult) -> list[OptionResult]:
    out = []
    lines = {line.payable_id: line for line in r.lines}
    targets = {e.payable_id: e.target_on for e in r.escalations}
    for p in sorted(s.payables, key=lambda p: p.payable_id):
        line = lines.get(p.payable_id)
        if p.priority != "flexible" or p.grace_days <= 0 or line is None or line.decision == "WAIT":
            continue
        delayed = replace(p, due_date=p.due_date + timedelta(days=p.grace_days), grace_days=0)
        from_day = line.pay_on or targets[p.payable_id]
        # The latest payment day within the grace days, even if it falls after the
        # horizon (then the rerun shows the bill as WAIT). If the grace days reach
        # no later payment day, delaying moves nothing and is not offered.
        to_day = latest_payment_day(s, s.today, delayed.due_date)
        if to_day is None or to_day <= from_day:
            continue
        rerun = plan(replace(s, payables=tuple(delayed if x is p else x for x in s.payables)))
        out.append(_from_rerun(
            "delay_flexible",
            {"payable_id": p.payable_id, "from_date": from_day.isoformat(),
             "to_date": to_day.isoformat()},
            rerun,
        ))
    return out


def options(s: PlanSnapshot, r: PlanResult) -> list[OptionResult]:
    if r.valid:
        return []
    out = _early_receipts(s, r) + _splits(s, r) + _delays(s, r)
    out.append(OptionResult(
        "authorise_breach",
        {"gap_paise": r.gap_paise, "lowest_on": r.lowest_on.isoformat()},
        r.lowest_balance_paise, r.lowest_on, False, None,
    ))
    # "The breach remains even with every non-statutory bill removed". Approved
    # payments (PAYMENT_EXPECTED) stay: they are commitments, not bills to remove.
    statutory_only = replace(
        s,
        payables=tuple(p for p in s.payables
                       if p.priority == "statutory" or p.status == "PAYMENT_EXPECTED"),
    )
    if not plan(statutory_only).valid:
        out.append(OptionResult("ask_ca", {}, None, None, False, None))
    return out
