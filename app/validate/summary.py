"""The number check on a plan summary (TDD Part 2, "Explaining a change";
batch 6, CHG-018). Gemini writes the "what changed" text from the plan diff;
this check lets it through only if every amount and every date in it is one
the diff holds. Any other digit, markup, or a text over 600 characters fails
it, and the caller uses a template built from the diff instead.

Amounts are read as written (₹1,83,000, Rs.1,83,000.00, 1,83,000); a sign is
presentation, so -₹20,000 matches ₹20,000 in the diff. Dates are Mon 12 Oct,
12 Oct, Oct 12, 12/10 (day first) and 2026-10-12; a weekday or a year, when
written, must agree with the diff's date."""

from __future__ import annotations

import re
from datetime import date

from app.domain.money import parse_inr
from app.validate import PASSED, failed

MAX_CHARS = 600
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_MONTH = r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_WEEKDAY = r"(?:(?P<weekday>mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s+(?P<year>\d{4}))?"

_CURRENCY = re.compile(r"(?P<sign>[-−]\s?)?(?:₹|rs\.?|inr)\s?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)", re.I)
_GROUPED = re.compile(r"(?P<sign>[-−]\s?)?\b(?P<amount>\d{1,3}(?:,\d{2})*,\d{3}(?:\.\d{1,2})?)\b")
_DATES = (
    re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b"),
    re.compile(r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})(?:/(?P<year>\d{4}|\d{2}))?\b"),
    re.compile(rf"\b{_WEEKDAY}{_DAY}\s+{_MONTH}{_YEAR}\b", re.I),
    re.compile(rf"\b{_WEEKDAY}{_MONTH}\s+{_DAY}{_YEAR}\b", re.I),
)


def _month(text: str) -> int:
    return int(text) if text.isdigit() else _MONTHS.index(text[:3].lower()) + 1


def _date_matches(m: re.Match[str], dates: frozenset[date]) -> bool:
    day, month = int(m["day"]), _month(m["month"])
    year = m.groupdict().get("year")
    weekday = m.groupdict().get("weekday")
    for d in dates:
        if (d.day, d.month) != (day, month):
            continue
        if year and (int(year) + 2000 if len(year) == 2 else int(year)) != d.year:
            continue
        if weekday and _DAYS.index(weekday[:3].lower()) != d.weekday():
            continue
        return True
    return False


def _unknown_amount(pattern: re.Pattern[str], text: str, amounts_paise: frozenset[int]) -> str | None:
    for m in pattern.finditer(text):
        try:
            value = parse_inr(m["amount"])
        except ValueError:
            return m.group(0).strip()
        if value not in amounts_paise and -value not in amounts_paise:
            return m.group(0).strip()
    return None


def check_summary(text: str, amounts_paise: frozenset[int], dates: frozenset[date]) -> str:
    """`passed`, or `failed: <the first thing not in the diff>`. Amounts with a
    currency mark are read first, then dates, then bare grouped amounts; any
    digit left over fails."""
    if len(text) > MAX_CHARS:
        return failed(f"longer than {MAX_CHARS} characters")
    if "<" in text or ">" in text or "](" in text:
        return failed("markup")
    bad = _unknown_amount(_CURRENCY, text, amounts_paise)
    if bad:
        return failed(f"amount {bad!r} is not in the plan's changes")
    rest = _CURRENCY.sub(" ", text)
    for pattern in _DATES:
        for m in pattern.finditer(rest):
            if not 1 <= _month(m["month"]) <= 12 or not _date_matches(m, dates):
                return failed(f"date {m.group(0).strip()!r} is not in the plan's changes")
        rest = pattern.sub(" ", rest)
    bad = _unknown_amount(_GROUPED, rest, amounts_paise)
    if bad:
        return failed(f"amount {bad!r} is not in the plan's changes")
    rest = _GROUPED.sub(" ", rest)
    stray = re.search(r"\d+", rest)
    if stray:
        return failed(f"number {stray.group(0)!r} is not an amount or date from the plan's changes")
    return PASSED
