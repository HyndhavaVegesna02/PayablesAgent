"""Shared setup for ledger-writer tests: a migrated DB with two businesses."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.clock import FakeClock
from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from app.domain.models import PayableNew

CLOCK_AT = datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def make_ledger_db(path: Path):
    """Business 1: owner 1, helper 2, account 1. Business 2: owner 3, account 2."""
    apply_migrations(path)
    conn = write_connection(path)
    conn.executescript(
        """
        INSERT INTO business (id, name, safety_amount_paise) VALUES (1, 'B1', 25000000), (2, 'B2', 0);
        INSERT INTO app_user (id, business_id, email, role, password_hash) VALUES
          (1, 1, 'o1@example.test', 'owner', '!'),
          (2, 1, 'h1@example.test', 'helper', '!'),
          (3, 2, 'o2@example.test', 'owner', '!');
        INSERT INTO bank_account (id, business_id, bank_name, account_name, account_mask,
                                  opening_balance_paise, opening_balance_at)
        VALUES (1, 1, 'HDFC', 'Current', 'XX01', 62000000, '2026-10-12'),
               (2, 2, 'SBI', 'Current', 'XX02', 0, '2026-10-12');
        """
    )
    conn.commit()
    return conn


def fake_clock() -> FakeClock:
    return FakeClock(CLOCK_AT)


def payable_new(**over) -> PayableNew:
    base = dict(
        business_id=1, party_id=None, invoice_number="INV-1", amount_paise=12_000_000,
        due_date=date(2026, 10, 22), priority="normal",
    )
    return PayableNew(**{**base, **over})


def events(conn, entity=None, entity_id=None):
    sql = "SELECT * FROM event"
    args = []
    if entity:
        sql += " WHERE entity = ? AND entity_id = ?"
        args = [entity, entity_id]
    return conn.execute(sql + " ORDER BY id", args).fetchall()
