from datetime import date, timedelta

from app.planner.forecast import DayBalance, Movement, opening_cash, project
from app.planner.plan import AccountCash

D = date(2026, 10, 12)


def test_project_accumulates_signed_movements_by_day():
    days = [D + timedelta(days=i) for i in range(4)]
    moves = [
        Movement(D, -18_000_000, "bill", 1),
        Movement(D + timedelta(days=1), 3_300_000, "inflow", 1),
        Movement(D + timedelta(days=3), -4_500_000, "bill", 2),
        Movement(D + timedelta(days=9), -1, "bill", 3),  # outside the days: ignored
    ]
    assert project(62_000_000, moves, days) == (
        DayBalance(D, 44_000_000),
        DayBalance(D + timedelta(days=1), 47_300_000),
        DayBalance(D + timedelta(days=2), 47_300_000),
        DayBalance(D + timedelta(days=3), 42_800_000),
    )


def test_opening_cash_sums_accounts():
    accounts = [AccountCash(1, 62_000_000, None, False), AccountCash(2, 1_000, 5_000, False)]
    assert opening_cash(accounts) == 62_001_000  # reported is ignored when there is no drift


def test_unresolved_drift_uses_the_lower_balance():
    assert opening_cash([AccountCash(1, 44_400_000, 41_200_000, True)]) == 41_200_000
    assert opening_cash([AccountCash(1, 41_200_000, 44_400_000, True)]) == 41_200_000


def test_drift_without_a_reported_balance_uses_calculated():
    assert opening_cash([AccountCash(1, 44_400_000, None, True)]) == 44_400_000


def test_no_accounts_means_no_cash():
    assert opening_cash([]) == 0
