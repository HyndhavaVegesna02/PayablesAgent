"""Presentation-only data for the templates: how many things wait for the
owner (the nav badge), the week chart's geometry, and the total of the
payments being approved. Integers throughout: the chart scales balances to
pixel heights and never changes a figure that is shown; every amount shown
is formatted by app.domain.money."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from app.db.read import build_snapshot
from app.domain.money import format_inr
from app.jobs.replan import inputs_sha256
from app.planner.plan import format_day
from app.web import repo


def needs_you(conn: sqlite3.Connection, business_id: int, today: date) -> int:
    """The things on Needs attention that wait for a decision: entries to
    confirm, open questions (a confirm_record question is its entry, already
    counted), balance mismatches, and an open shortfall choice."""
    count = len(repo.waiting_candidates(conn, business_id))
    count += sum(1 for q in repo.open_questions(conn, business_id) if q["kind"] != "confirm_record")
    count += len(repo.accounts_not_ok(conn, business_id))
    run = repo.current_run(conn, business_id)
    if run is not None:
        opts = repo.options(conn, business_id, run["id"], today=today)
        if opts and not any(o.chosen or o.pending for o in opts):
            count += 1
    return count


def when(stamp: str | None) -> str:
    """An ISO timestamp as "Mon 12 Oct, 07:00" (its own time zone)."""
    if not stamp:
        return ""
    t = datetime.fromisoformat(stamp)
    return f"{format_day(t.date())}, {t:%H:%M}"


def when_day(stamp: str | None) -> str:
    """An ISO timestamp's day as "Tue 13 Oct"."""
    return format_day(datetime.fromisoformat(stamp).date()) if stamp else ""


@dataclass(frozen=True)
class Bar:
    x: int
    y: int
    height: int
    below: bool
    lowest: bool
    today: bool
    label: str  # the day of the month under the bar


@dataclass(frozen=True)
class Chart:
    width: int
    height: int
    bar_width: int
    baseline: int
    safety_y: int
    bars: list[Bar]
    summary: str  # the chart as one sentence, for screen readers


PLOT = 150  # plot height in viewBox units
TOP = 14  # room above the tallest bar
STEP = 40
BAR = 26


def chart(view: repo.PlanView, today: date) -> Chart | None:
    if not view.days:
        return None
    balances = [d.balance_paise for d in view.days]
    top = max(max(balances), view.safety_paise, 1)
    baseline = TOP + PLOT
    bars = []
    for i, d in enumerate(view.days):
        h = max(d.balance_paise, 0) * PLOT // top
        h = max(h, 2)  # a zero or negative day still shows as a sliver on the floor
        bars.append(Bar(i * STEP + (STEP - BAR) // 2, baseline - h, h, d.below,
                        d.day == view.lowest_on, d.day == today, str(d.day.day)))
    first, last = view.days[0].day, view.days[-1].day
    below = [d for d in view.days if d.below]
    said = (f"Projected end-of-day balance from {format_day(first)} to {format_day(last)}. "
            f"Safety amount {format_inr(view.safety_paise)}. ")
    if below:
        said += (f"It is below the safety amount on {len(below)} of {len(view.days)} days, from "
                 f"{format_day(below[0].day)}; lowest {format_inr(view.lowest_balance_paise)} on "
                 f"{format_day(view.lowest_on)}.")
    else:
        said += (f"It stays above the safety amount every day; lowest {format_inr(view.lowest_balance_paise)} "
                 f"on {format_day(view.lowest_on)}.")
    return Chart(width=len(view.days) * STEP, height=baseline + 26, bar_width=BAR, baseline=baseline,
                 safety_y=baseline - view.safety_paise * PLOT // top, bars=bars, summary=said)


def below_span(view: repo.PlanView) -> tuple[date, date] | None:
    """The first and last day below the safety amount, for the chart's legend."""
    below = [d.day for d in view.days if d.below]
    return (below[0], below[-1]) if below else None


@dataclass(frozen=True)
class MoneyIn:
    name: str
    amount_paise: int


def money_in(conn: sqlite3.Connection, business_id: int, view: repo.PlanView) -> dict[date, list[MoneyIn]]:
    """The customer payments the plan counted, by day: the snapshot's inflows
    inside the plan's days, as the planner adds them. Only shown when the
    snapshot rebuilt for the plan's day hashes to the run's inputs_sha256, so
    the lines are exactly what the day balances were planned from; otherwise
    (inputs changed since) none are shown rather than a guess."""
    if not view.days:
        return {}
    first, last = view.days[0].day, view.days[-1].day
    snapshot = build_snapshot(conn, business_id, first)
    if inputs_sha256(snapshot) != view.run["inputs_sha256"]:
        return {}
    names = repo.receivable_names(conn, business_id)
    out: dict[date, list[MoneyIn]] = {}
    for i in sorted(snapshot.inflows, key=lambda i: (i.expected_date, i.receivable_id)):
        if first <= i.expected_date <= last:
            out.setdefault(i.expected_date, []).append(
                MoneyIn(names.get(i.receivable_id, "A customer"), i.amount_paise))
    return out


def total_paise(lines: list[repo.Line]) -> int:
    """The sum of the payments being approved (integer paise), for the summary above the button."""
    return sum(ln.amount_paise for ln in lines)
