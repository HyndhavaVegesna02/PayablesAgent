from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.clock import FakeClock, SystemClock


def test_system_clock_is_tz_aware_asia_kolkata():
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=5, minutes=30)
    assert clock.today() == now.date()


def test_fake_clock_returns_fixed_time_until_advanced():
    start = datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    clock = FakeClock(start)

    assert clock.now() == start
    assert clock.today() == date(2026, 10, 12)

    clock.advance(timedelta(days=1, hours=2))

    assert clock.now() == start + timedelta(days=1, hours=2)
    assert clock.today() == date(2026, 10, 13)


def test_fake_clock_is_deterministic_across_repeated_reads():
    clock = FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    first = clock.now()
    second = clock.now()
    assert first == second
