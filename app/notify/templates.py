"""The owner alert texts (TDD Part 1, the alert table; batch 7, CHG-010b).
Fixed sentences; code fills in only figures and names it read from the
ledger. A name is cleaned to one short line, so it can add no line or header
to the email, and anything shaped like a web address is cut out of it, so a
vendor's name can't put a link in front of the owner (TDD Part 1, "Messages").
The subject holds no stored text at all."""

from __future__ import annotations

import re

from app.domain.money import format_inr

MAX_NAME = 60


# Control characters, the line and paragraph separators, and the bidi controls
# (which can make a name read backwards on screen).
_UNSAFE = re.compile("[\\x00-\\x1f\\x7f\\u2028\\u2029\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]+")
# A scheme (http://, ftp://), www., an email address, or a dotted name ending in
# a common top-level domain.
_ADDRESS = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]*://|www\.)\S*|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
                      r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|in|io|co|info|biz|xyz|app|example)\b\S*")


def clean(name: str | None) -> str:
    """One printable line of at most 60 characters, with no web address."""
    text = _UNSAFE.sub(" ", name or "")
    text = _ADDRESS.sub("[link removed]", text)
    text = " ".join(text.split())
    return (text[:MAX_NAME - 1] + "…") if len(text) > MAX_NAME else (text or "someone")


def money_received(amount_paise: int, party: str | None, lowest_paise: int | None) -> str:
    after = f" Lowest projected balance is now {format_inr(lowest_paise)}." if lowest_paise is not None else ""
    return f"{format_inr(amount_paise)} received from {clean(party)}.{after} Plan updated."


def payment_failed(amount_paise: int, party: str | None) -> str:
    return (f"The {format_inr(amount_paise)} payment to {clean(party)} was returned. "
            "The bill is reopened and the plan updated.")


def payment_failed_unmatched(amount_paise: int) -> str:
    return (f"A {format_inr(amount_paise)} payment failed or was returned, and no single bill matches it. "
            "Please look at it.")


def unexpected_debit(amount_paise: int, bank: str | None) -> str:
    return f"A {format_inr(amount_paise)} debit from {clean(bank)} wasn't in the plan. What was it for?"


def balance_mismatch(bank: str | None, reported_paise: int, calculated_paise: int) -> str:
    return (f"{clean(bank)} shows {format_inr(reported_paise)}; I calculate {format_inr(calculated_paise)}. "
            f"Difference {format_inr(abs(reported_paise - calculated_paise))}. What is the actual balance?")


def digest(lines: list[str], link: str) -> tuple[str, str]:
    """(subject, body) for one email holding every unsent alert."""
    subject = "Cash-flow assistant: 1 thing needs you" if len(lines) == 1 else \
        f"Cash-flow assistant: {len(lines)} things need you"
    body = "\n".join(f"- {line}" for line in lines)
    return subject, (f"{body}\n\nOpen the app to see and answer them: {link}\n\n"
                     "This email was written by code from your records. The assistant cannot send email.\n")
