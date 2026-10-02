"""Daily balance projection (TDD Part 2, "Planning engine", steps 1, 2 and 4)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

MovementSource = Literal["inflow", "commitment", "payment_expected", "bill"]


@dataclass(frozen=True)
class Movement:
    """One dated change to cash; outflows are negative. `ref_id` names the
    snapshot record it came from, so every rupee in a forecast traces back."""

    day: date
    amount_paise: int
    source: MovementSource
    ref_id: int


@dataclass(frozen=True)
class DayBalance:
    day: date
    balance_paise: int


class _Account(Protocol):
    calculated_paise: int
    reported_paise: int | None
    drift_unresolved: bool


def opening_cash(accounts: Iterable[_Account]) -> int:
    """Sum of balances; an account with unresolved drift counts at the lower of
    its calculated and reported balance, so an open mismatch never flatters."""
    total = 0
    for a in accounts:
        if a.drift_unresolved and a.reported_paise is not None:
            total += min(a.calculated_paise, a.reported_paise)
        else:
            total += a.calculated_paise
    return total


def project(opening: int, movements: Iterable[Movement], days: Sequence[date]) -> tuple[DayBalance, ...]:
    by_day: dict[date, int] = {}
    for m in movements:
        by_day[m.day] = by_day.get(m.day, 0) + m.amount_paise
    balance = opening
    out = []
    for d in days:
        balance += by_day.get(d, 0)
        out.append(DayBalance(d, balance))
    return tuple(out)
