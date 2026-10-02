"""Clock interface: all code reads time through this, never datetime.now()
or date.today() directly, so the scenario suite can replay a fortnight in
seconds. See TDD Part 2, "What this design adds to the TDD" (Time)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Kolkata")


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    """Real wall-clock time, in Asia/Kolkata."""

    def now(self) -> datetime:
        return datetime.now(tz=TIMEZONE)

    def today(self) -> date:
        return self.now().date()


class FakeClock:
    """Fixed time until explicitly advanced. For tests and evals."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._at = at

    def advance(self, delta: timedelta) -> None:
        self._at = self._at + delta

    def now(self) -> datetime:
        return self._at

    def today(self) -> date:
        return self._at.date()
