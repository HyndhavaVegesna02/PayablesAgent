"""The dates check for mail (TDD Part 1, "Rule checks", Dates). An alert's
transaction date cannot be after the email was sent, and an alert arrives
within days of the transaction, so one dated more than a week before its
email is a misreading."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.domain.time import TIMEZONE
from app.validate import PASSED, failed

MAX_ALERT_AGE = timedelta(days=7)


def check_mail_date(event_date: date, sent_at: datetime | None, what: str = "transaction") -> str:
    if sent_at is None:
        return failed("the email has no readable Date header")
    sent = sent_at.astimezone(TIMEZONE).date()
    if event_date > sent:
        return failed(f"{what} date {event_date} is after the email was sent ({sent})")
    if event_date < sent - MAX_ALERT_AGE:
        return failed(f"{what} date {event_date} is more than 7 days before the email ({sent})")
    return PASSED
