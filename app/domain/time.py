"""The business's time zone. A constant, so pure code (app/validate, the
planner) can turn an aware datetime into a local date without importing the
clock; reading the time itself is still only app/clock.py's job."""

from __future__ import annotations

from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Kolkata")
