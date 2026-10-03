"""The duplicates check (TDD Part 1, "Rule checks": same amount, date and
reference). The dedup key is built by code from what was extracted, never by
the model, and bank_txn.dedup_key is UNIQUE, so a transaction cannot be
written twice even if this check were skipped. The lookups that read
the database live in app/db/read.py; this module stays pure."""

from __future__ import annotations

from datetime import date


def normalise_reference(reference: str | None) -> str | None:
    if reference is None:
        return None
    ref = "".join(reference.split()).upper()
    return ref or None


def normalise_invoice_number(number: str | None) -> str | None:
    """Letters and digits only, upper case: "AP/2610/131", "ap-2610-131" and
    "AP 2610 131" are one invoice number. (Bank references keep their
    punctuation: their dedup keys are stored.)"""
    if number is None:
        return None
    n = "".join(ch for ch in number.upper() if ch.isalnum())
    return n or None


def txn_dedup_key(account_id: int, txn_date: date, direction: str, amount_paise: int,
                  reference: str | None) -> str:
    return f"{account_id}:{txn_date.isoformat()}:{direction}:{amount_paise}:{normalise_reference(reference) or '-'}"


def failure_dedup_key(account_id: int, failure_date: date, amount_paise: int,
                      original_reference: str | None) -> str:
    return f"failure:{account_id}:{failure_date.isoformat()}:{amount_paise}:{normalise_reference(original_reference) or '-'}"
