"""The TDD Part 1 worked example as a hand-built PlanSnapshot (golden input)."""

from __future__ import annotations

from datetime import date

from app.planner.plan import AccountCash, InflowIn, PayableIn, PlanSnapshot

TODAY = date(2026, 10, 12)  # Monday
MON_THU = frozenset({0, 3})


def oct(day: int) -> date:
    return date(2026, 10, day)


def worked_example() -> PlanSnapshot:
    return PlanSnapshot(
        today=TODAY,
        horizon_days=14,
        payment_days=MON_THU,
        safety_paise=25_000_000,
        accounts=(AccountCash(1, 62_000_000, None, False),),
        payables=(
            PayableIn(1, 18_000_000, oct(14), "normal"),      # Paper supplier
            PayableIn(2, 4_500_000, oct(15), "statutory"),    # PF and ESI
            PayableIn(3, 3_500_000, oct(16), "critical"),     # Electricity
            PayableIn(4, 9_000_000, oct(20), "statutory"),    # GST
            PayableIn(5, 12_000_000, oct(22), "normal"),      # Prime Chem
        ),
        inflows=(InflowIn(1, 3_300_000, oct(13), "COMMITTED"),),           # Kaveri
        commitments=(),
        uncounted_inflows=(InflowIn(2, 20_000_000, oct(28), "EXPECTED"),),  # Nandi
    )


def snapshot(**over) -> PlanSnapshot:
    base = dict(
        today=TODAY, horizon_days=14, payment_days=MON_THU, safety_paise=0,
        accounts=(AccountCash(1, 100_000_000, None, False),), payables=(), inflows=(),
        commitments=(), uncounted_inflows=(),
    )
    return PlanSnapshot(**{**base, **over})


# Part 1, "Projected end-of-day balance", in paise.
ORIGINAL_PLAN = [
    44_000_000, 47_300_000, 47_300_000, 39_300_000, 39_300_000, 39_300_000, 39_300_000,
    30_300_000, 30_300_000, 30_300_000, 18_300_000, 18_300_000, 18_300_000, 18_300_000,
]
NANDI_PAYS_FRI_16 = [
    44_000_000, 47_300_000, 47_300_000, 39_300_000, 59_300_000, 59_300_000, 59_300_000,
    50_300_000, 50_300_000, 50_300_000, 38_300_000, 38_300_000, 38_300_000, 38_300_000,
]
