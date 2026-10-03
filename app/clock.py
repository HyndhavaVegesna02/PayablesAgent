"""Clock interface: all code reads time through this, never datetime.now()
or date.today() directly, so the scenario suite can replay a fortnight in
seconds. See TDD Part 2, "What this design adds to the TDD" (Time)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Kolkata")
_T = TypeVar("_T")


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


DEMO_CLOCK_FILE = "demo_clock.txt"


class DemoClock:
    """Demo mode's one "now" (batch 3 plan, PO decision D14). The instant lives
    in a file under DATA_DIR, so the web app and the worker read the same
    time; it starts at DEMO_NOW and stands still until `make demo-time` or
    the owner's demo form moves it forward."""

    def __init__(self, path: str | Path, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("DemoClock requires a timezone-aware start")
        self.path = Path(path)
        self.start = start

    def now(self) -> datetime:
        try:
            text = _shared(lambda: self.path.read_text(encoding="utf-8")).strip()
        except FileNotFoundError:
            return self.start.astimezone(TIMEZONE)
        return datetime.fromisoformat(text).astimezone(TIMEZONE)

    def today(self) -> date:
        return self.now().date()

    def set(self, at: datetime) -> datetime:
        """Moves the demo forward to `at`; returns the previous instant."""
        if at.tzinfo is None:
            raise ValueError("the demo time needs a UTC offset, like 2026-10-15T09:00:00+05:30")
        before = self.now()
        if at < before:
            raise ValueError(f"the demo clock only moves forward; it is already {before.isoformat()}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(at.astimezone(TIMEZONE).isoformat(), encoding="utf-8")
        _shared(lambda: tmp.replace(self.path))
        return before

    def reset(self) -> None:
        """Back to DEMO_NOW (make reseed)."""
        _shared(lambda: self.path.unlink(missing_ok=True))


def _shared(op: Callable[[], _T], attempts: int = 200, pause_s: float = 0.005) -> _T:
    """Runs a file operation on the demo clock file. Windows refuses to read a
    file another process is replacing, or to replace one another process is
    reading, with PermissionError; the web app and the worker both use this
    file, so a refusal is retried briefly (about a second at most), the same
    tolerance the worker's heartbeat has."""
    for _ in range(attempts - 1):
        try:
            return op()
        except PermissionError:
            time.sleep(pause_s)
    return op()


def clock_for(demo_now: str, data_dir: str | Path) -> Clock:
    """The clock for a process: real time, or with DEMO_NOW set the demo clock
    every process shares (D14). Nothing else differs between the two modes."""
    if not demo_now:
        return SystemClock()
    return DemoClock(Path(data_dir) / DEMO_CLOCK_FILE, datetime.fromisoformat(demo_now))
