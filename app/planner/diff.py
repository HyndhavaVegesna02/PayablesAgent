"""What changed between two plan runs (TDD Part 2, "Explaining a change").

explain_plan will hand this list to Gemini for a plain-text summary; the
check that guards that summary rejects any amount or date not in
`amounts_paise` / `dates`, so both sets hold exactly what the changes mention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from app.planner.plan import PlanLine

ChangeKind = Literal["opening_cash", "lowest", "validity", "line_added", "line_removed", "line_changed"]


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    payable_id: int | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class PlanDiff:
    changes: tuple[Change, ...]  # summary changes first, then lines by payable_id
    amounts_paise: frozenset[int]
    dates: frozenset[date]


class PlanFigures(Protocol):
    """What diff() reads of a plan: a PlanResult, or a stored run rebuilt by
    app.db.read.persisted_result (which keeps no day-by-day schedule)."""

    @property
    def opening_cash_paise(self) -> int: ...
    @property
    def lowest_balance_paise(self) -> int: ...
    @property
    def lowest_on(self) -> date: ...
    @property
    def valid(self) -> bool: ...
    @property
    def lines(self) -> tuple[PlanLine, ...]: ...


def _line(line: PlanLine) -> dict[str, Any]:
    return {"decision": line.decision, "pay_on": line.pay_on, "amount_paise": line.amount_paise}


def diff(old: PlanFigures, new: PlanFigures) -> PlanDiff:
    changes: list[Change] = []
    if old.opening_cash_paise != new.opening_cash_paise:
        changes.append(Change("opening_cash", None, {"amount_paise": old.opening_cash_paise},
                              {"amount_paise": new.opening_cash_paise}))
    if (old.lowest_balance_paise, old.lowest_on) != (new.lowest_balance_paise, new.lowest_on):
        changes.append(Change("lowest", None,
                              {"amount_paise": old.lowest_balance_paise, "on": old.lowest_on},
                              {"amount_paise": new.lowest_balance_paise, "on": new.lowest_on}))
    if old.valid != new.valid:
        changes.append(Change("validity", None, {"valid": old.valid}, {"valid": new.valid}))

    before = {line.payable_id: _line(line) for line in old.lines}
    after = {line.payable_id: _line(line) for line in new.lines}
    for pid in sorted(before.keys() | after.keys()):
        if pid not in after:
            changes.append(Change("line_removed", pid, before[pid], None))
        elif pid not in before:
            changes.append(Change("line_added", pid, None, after[pid]))
        elif before[pid] != after[pid]:
            changes.append(Change("line_changed", pid, before[pid], after[pid]))

    amounts: set[int] = set()
    dates: set[date] = set()
    for c in changes:
        for side in (c.before, c.after):
            for key, value in (side or {}).items():
                if key.endswith("_paise"):
                    amounts.add(value)
                elif isinstance(value, date):
                    dates.add(value)
    return PlanDiff(tuple(changes), frozenset(amounts), frozenset(dates))
