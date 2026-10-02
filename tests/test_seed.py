import sqlite3

import pytest

from app.db.migrate import apply_migrations
from fixtures.seed import seed


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "seed-test.db"
    apply_migrations(db_path)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_seed_creates_worked_example_business(conn):
    seed(conn)

    business = conn.execute("SELECT * FROM business WHERE id = 1").fetchone()
    assert business is not None
    assert business["safety_amount_paise"] == 25_000_000  # ₹2,50,000
    assert business["payment_days"] == "MON,THU"
    assert business["horizon_days"] == 14


def test_seed_creates_the_bank_account_with_observed_cash(conn):
    seed(conn)

    row = conn.execute(
        "SELECT calculated_balance_paise FROM account_balance ab "
        "JOIN bank_account a ON a.id = ab.account_id WHERE a.business_id = 1"
    ).fetchone()
    assert row["calculated_balance_paise"] == 62_000_000  # ₹6,20,000, no txns yet


def test_seed_creates_five_payables_matching_the_worked_example(conn):
    seed(conn)

    payables = {
        row["invoice_number"]: (row["amount_paise"], row["due_date"], row["priority"])
        for row in conn.execute(
            "SELECT * FROM payable WHERE business_id = 1"
        ).fetchall()
    }
    assert len(payables) == 5
    assert payables["PAPER-001"] == (18_000_000, "2026-10-14", "normal")
    assert payables["PFESI-OCT26"] == (4_500_000, "2026-10-15", "statutory")
    assert payables["ELEC-OCT26"] == (3_500_000, "2026-10-16", "critical")
    assert payables["GST-OCT26"] == (9_000_000, "2026-10-20", "statutory")
    assert payables["PRIME-001"] == (12_000_000, "2026-10-22", "normal")

    # Prime Chem has no grace days (TDD: "no grace days")
    prime = conn.execute(
        "SELECT grace_days FROM payable WHERE invoice_number = 'PRIME-001'"
    ).fetchone()
    assert prime["grace_days"] == 0

    statuses = {
        row["status"] for row in conn.execute("SELECT status FROM payable").fetchall()
    }
    assert statuses == {"CONFIRMED"}


def test_seed_creates_two_receivables_with_correct_confidence(conn):
    seed(conn)

    receivables = {
        row["invoice_number"]: (row["amount_paise"], row["expected_date"], row["confidence"])
        for row in conn.execute(
            "SELECT * FROM receivable WHERE business_id = 1"
        ).fetchall()
    }
    assert receivables["KAVERI-001"] == (3_300_000, "2026-10-13", "COMMITTED")
    assert receivables["NANDI-001"] == (20_000_000, "2026-10-28", "EXPECTED")


def test_seed_is_idempotent(conn):
    seed(conn)
    seed(conn)  # must not raise a UNIQUE constraint error

    count = conn.execute("SELECT COUNT(*) FROM business").fetchone()[0]
    assert count == 1
    payable_count = conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0]
    assert payable_count == 5
