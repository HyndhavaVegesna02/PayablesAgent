"""plan(snapshot) -> PlanResult (TDD Part 2, "Planning engine").

A pure function: the same snapshot gives the same plan, byte for byte
(canonical_json). It reads no clock, database or network; the caller builds
the snapshot (app.db.read.build_snapshot) and stores the result.

Rules the TDD leaves implicit are pinned here and locked by tests (batch 1
plan, CHG-003 "Algorithm"; PO decisions D8 and D9):
- A bill due after the horizon gets WAIT.
- Otherwise its target is the latest payment day in [today, due date]; if
  there is none (overdue, or no payment day before the due date) it is the
  next payment day on or after today, today included. No such day inside the
  horizon -> WAIT.
- A discount (paise saved if paid by discount_by) is tried first; if paying
  early would breach, the bill falls back to its normal target at full amount
  and only escalates if that breaches too (D9).
- The plan is valid when nothing is escalated and no day of the full
  schedule is below the safety amount.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from app.domain.money import format_inr
from app.planner.forecast import DayBalance, Movement, opening_cash, project

Priority = Literal["statutory", "critical", "normal", "flexible"]
Decision = Literal["PAY", "WAIT", "ESCALATE"]
PRIORITY_ORDER = {"statutory": 0, "critical": 1, "normal": 2, "flexible": 3}

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --- snapshot (input) -----------------------------------------------------------


@dataclass(frozen=True)
class AccountCash:
    account_id: int
    calculated_paise: int
    reported_paise: int | None
    drift_unresolved: bool


@dataclass(frozen=True)
class PayableIn:
    payable_id: int
    amount_paise: int
    due_date: date
    priority: Priority
    grace_days: int = 0
    discount_paise: int | None = None
    discount_by: date | None = None
    status: Literal["CONFIRMED", "PLANNED", "REOPENED", "PAYMENT_EXPECTED"] = "CONFIRMED"
    planned_date: date | None = None


@dataclass(frozen=True)
class InflowIn:
    receivable_id: int
    amount_paise: int
    expected_date: date
    confidence: Literal["COMMITTED", "EXPECTED"]


@dataclass(frozen=True)
class CommitmentIn:
    commitment_id: int
    day: date
    amount_paise: int
    label: str


@dataclass(frozen=True)
class PlanSnapshot:
    today: date
    horizon_days: int
    payment_days: frozenset[int]  # 0 = Monday
    safety_paise: int
    accounts: tuple[AccountCash, ...]
    payables: tuple[PayableIn, ...]  # CONFIRMED, PLANNED, REOPENED, PAYMENT_EXPECTED
    inflows: tuple[InflowIn, ...]  # COMMITTED receivables dated inside the horizon
    commitments: tuple[CommitmentIn, ...]  # fixed outflows; always () in the MVP (D1)
    # PO-approved addition (D8): EXPECTED receivables and COMMITTED ones dated after
    # the horizon. Never counted; read only by the early_receipt option.
    uncounted_inflows: tuple[InflowIn, ...] = ()


# --- result (output) ------------------------------------------------------------


@dataclass(frozen=True)
class PlanLine:
    payable_id: int
    decision: Decision
    pay_on: date | None
    amount_paise: int
    reason: str


@dataclass(frozen=True)
class Escalation:
    payable_id: int
    breach_on: date
    lowest_paise: int
    lowest_on: date
    gap_paise: int


@dataclass(frozen=True)
class PlanResult:
    today: date
    horizon_end: date
    opening_cash_paise: int
    safety_paise: int
    days: tuple[DayBalance, ...]  # the full schedule (step 4): what plan_day stores
    movements: tuple[Movement, ...]
    lines: tuple[PlanLine, ...]  # sorted by payable_id; none for PAYMENT_EXPECTED bills
    escalations: tuple[Escalation, ...]
    lowest_balance_paise: int
    lowest_on: date
    breach_on: date | None  # first full-schedule day below the safety amount
    gap_paise: int  # safety amount minus the lowest balance, when below
    valid: bool


# --- helpers --------------------------------------------------------------------


def format_day(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"


def horizon(s: PlanSnapshot) -> tuple[date, ...]:
    if s.horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    return tuple(s.today + timedelta(days=i) for i in range(s.horizon_days))


def _latest_payment_day(s: PlanSnapshot, start: date, end: date) -> date | None:
    d = end
    while d >= start:
        if d.weekday() in s.payment_days:
            return d
        d -= timedelta(days=1)
    return None


def _next_payment_day(s: PlanSnapshot, start: date) -> date | None:
    for i in range(7):
        d = start + timedelta(days=i)
        if d.weekday() in s.payment_days:
            return d
    return None


@dataclass(frozen=True)
class _Target:
    day: date
    amount_paise: int
    why: str  # the reason text after "Pay ₹X on <day>: "


def _normal_target(s: PlanSnapshot, p: PayableIn) -> _Target | None:
    d = _latest_payment_day(s, s.today, p.due_date)
    if d is not None:
        why = f"latest payment day on or before the due date ({format_day(p.due_date)})"
    else:
        d = _next_payment_day(s, s.today)
        if d is None:
            return None
        if p.due_date < s.today:
            why = f"overdue since {format_day(p.due_date)}; next payment day"
        else:
            why = f"no payment day between today and the due date ({format_day(p.due_date)}); next payment day"
    return _Target(d, p.amount_paise, why)


def _discount_target(s: PlanSnapshot, p: PayableIn) -> _Target | None:
    if not p.discount_paise or p.discount_by is None:
        return None
    d = _latest_payment_day(s, s.today, min(p.discount_by, p.due_date))
    if d is None:
        return None
    return _Target(
        d,
        p.amount_paise - p.discount_paise,
        f"by the discount date ({format_day(p.discount_by)}), saving {format_inr(p.discount_paise)}",
    )


def _after(curve: dict[date, int], days: tuple[date, ...], start: date, amount: int):
    """Balances from `start` onward if `amount` is paid on `start`."""
    return [(d, curve[d] - amount) for d in days if d >= start]


def _fits(curve, days, t: _Target, safety: int) -> bool:
    return all(b >= safety for _, b in _after(curve, days, t.day, t.amount_paise))


def _breach(curve, days, t: _Target, safety: int, payable_id: int) -> Escalation:
    after = _after(curve, days, t.day, t.amount_paise)
    breach_on = next(d for d, b in after if b < safety)
    lowest_on, lowest = min(after, key=lambda x: (x[1], x[0]))
    return Escalation(payable_id, breach_on, lowest, lowest_on, safety - lowest)


def _breach_text(e: Escalation) -> str:
    return (
        f"below the safety amount from {format_day(e.breach_on)}: lowest "
        f"{format_inr(e.lowest_paise)} on {format_day(e.lowest_on)}, {format_inr(e.gap_paise)} below"
    )


# --- the planner ----------------------------------------------------------------


def plan(s: PlanSnapshot) -> PlanResult:
    days = horizon(s)
    first, last = days[0], days[-1]
    opening = opening_cash(s.accounts)

    base: list[Movement] = []
    for i in s.inflows:
        if first <= i.expected_date <= last:
            base.append(Movement(i.expected_date, i.amount_paise, "inflow", i.receivable_id))
    for c in s.commitments:
        if first <= c.day <= last:
            base.append(Movement(c.day, -c.amount_paise, "commitment", c.commitment_id))
    for p in s.payables:
        if p.status == "PAYMENT_EXPECTED":
            # Approved but not yet seen leaving the bank: counted on its planned day,
            # or today if that day has passed (or is unknown).
            day = max(p.planned_date or first, first)
            if day <= last:
                base.append(Movement(day, -p.amount_paise, "payment_expected", p.payable_id))

    curve = {b.day: b.balance_paise for b in project(opening, base, days)}
    lines: dict[int, PlanLine] = {}
    escalations: list[Escalation] = []
    bill_moves: list[Movement] = []

    plannable = sorted(
        (p for p in s.payables if p.status != "PAYMENT_EXPECTED"),
        key=lambda p: (PRIORITY_ORDER[p.priority], p.due_date, p.payable_id),
    )
    for p in plannable:
        normal = _normal_target(s, p) if p.due_date <= last else None
        if normal is None or normal.day > last:
            if p.due_date > last:
                why = f"due {format_day(p.due_date)}, after the planning horizon (ends {format_day(last)})"
            else:
                why = f"no payment day in the planning horizon (ends {format_day(last)})"
            lines[p.payable_id] = PlanLine(p.payable_id, "WAIT", None, p.amount_paise, f"Wait: {why}.")
            continue

        discount = _discount_target(s, p)
        chosen: _Target | None = None
        note = ""
        if discount is not None and _fits(curve, days, discount, s.safety_paise):
            chosen = discount
        else:
            if discount is not None:
                note = (
                    f" Early-payment discount of {format_inr(p.discount_paise)} skipped: paying "
                    f"{format_inr(discount.amount_paise)} on {format_day(discount.day)} would take "
                    f"the balance below the safety amount."
                )
            if _fits(curve, days, normal, s.safety_paise):
                chosen = normal

        if chosen is not None:
            reason = f"Pay {format_inr(chosen.amount_paise)} on {format_day(chosen.day)}: {chosen.why}.{note}"
        elif p.priority == "statutory":
            # Statutory bills are always paid on time; the breach makes the plan invalid.
            chosen = normal
            e = _breach(curve, days, normal, s.safety_paise, p.payable_id)
            reason = (
                f"Pay {format_inr(normal.amount_paise)} on {format_day(normal.day)}: statutory, paid "
                f"on time although it takes the balance {_breach_text(e)}.{note}"
            )
        else:
            e = _breach(curve, days, normal, s.safety_paise, p.payable_id)
            escalations.append(e)
            lines[p.payable_id] = PlanLine(
                p.payable_id, "ESCALATE", None, p.amount_paise,
                f"Paying {format_inr(normal.amount_paise)} on {format_day(normal.day)} takes the "
                f"balance {_breach_text(e)}.{note}",
            )
            bill_moves.append(Movement(normal.day, -normal.amount_paise, "bill", p.payable_id))
            continue

        lines[p.payable_id] = PlanLine(p.payable_id, "PAY", chosen.day, chosen.amount_paise, reason)
        bill_moves.append(Movement(chosen.day, -chosen.amount_paise, "bill", p.payable_id))
        for d in days:
            if d >= chosen.day:
                curve[d] -= chosen.amount_paise

    movements = tuple(
        sorted(base + bill_moves, key=lambda m: (m.day, m.source, m.ref_id, m.amount_paise))
    )
    full = project(opening, movements, days)
    lowest = min(full, key=lambda b: (b.balance_paise, b.day))
    breach_on = next((b.day for b in full if b.balance_paise < s.safety_paise), None)
    return PlanResult(
        today=s.today,
        horizon_end=last,
        opening_cash_paise=opening,
        safety_paise=s.safety_paise,
        days=full,
        movements=movements,
        lines=tuple(lines[k] for k in sorted(lines)),
        escalations=tuple(sorted(escalations, key=lambda e: e.payable_id)),
        lowest_balance_paise=lowest.balance_paise,
        lowest_on=lowest.day,
        breach_on=breach_on,
        gap_paise=max(0, s.safety_paise - lowest.balance_paise),
        valid=not escalations and lowest.balance_paise >= s.safety_paise,
    )


# --- canonical encoding ---------------------------------------------------------


def _plain(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (frozenset, set)):
        return sorted(_plain(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, float):
        raise TypeError("floats never appear in planner output")
    return obj


def canonical_json(obj: Any) -> bytes:
    """Sorted keys, ISO dates, ints only: the byte-identical form of a plan."""
    return json.dumps(_plain(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
