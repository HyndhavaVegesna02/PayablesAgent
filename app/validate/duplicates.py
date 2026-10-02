"""The duplicates check (TDD Part 1, "Rule checks": same amount, date and
reference). The dedup key is built by code from what was extracted, never by
the model, and bank_txn.dedup_key is UNIQUE, so a transaction cannot be
written twice even if this check were skipped."""

from __future__ import annotations

import sqlite3
from datetime import date


def normalise_reference(reference: str | None) -> str | None:
    if reference is None:
        return None
    ref = "".join(reference.split()).upper()
    return ref or None


def txn_dedup_key(account_id: int, txn_date: date, direction: str, amount_paise: int,
                  reference: str | None) -> str:
    return f"{account_id}:{txn_date.isoformat()}:{direction}:{amount_paise}:{normalise_reference(reference) or '-'}"


def failure_dedup_key(account_id: int, failure_date: date, amount_paise: int,
                      original_reference: str | None) -> str:
    return f"failure:{account_id}:{failure_date.isoformat()}:{amount_paise}:{normalise_reference(original_reference) or '-'}"


def bank_txn_with_key(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute("SELECT id FROM bank_txn WHERE dedup_key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def failure_candidate_with_key(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM candidate WHERE status IN ('VALID', 'ACCEPTED') "
        "AND json_extract(payload_json, '$.dedup_key') = ?", (key,)
    ).fetchone()
    return None if row is None else row[0]
