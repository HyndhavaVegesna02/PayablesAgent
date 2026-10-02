"""Loads the worked-example business from TDD Part 1, "Worked example".
Every figure here reconciles (it doubles as the planner's golden test seed),
so changing a number here without re-checking that section will break
CHG-003's golden test later.

Idempotent: re-running wipes business_id=1's data and reloads it, so
`make seed` is safe to run more than once against the same database.
"""

from __future__ import annotations

import os
import sqlite3

from app.db.migrate import apply_migrations

BUSINESS_ID = 1


def seed(conn: sqlite3.Connection) -> None:
    # Wipe any previous seed for this business (idempotent re-run), children first.
    conn.execute("DELETE FROM payable WHERE business_id = ?", (BUSINESS_ID,))
    conn.execute("DELETE FROM receivable WHERE business_id = ?", (BUSINESS_ID,))
    conn.execute("DELETE FROM bank_account WHERE business_id = ?", (BUSINESS_ID,))
    conn.execute("DELETE FROM party WHERE business_id = ?", (BUSINESS_ID,))
    conn.execute("DELETE FROM business WHERE id = ?", (BUSINESS_ID,))

    conn.execute(
        """
        INSERT INTO business
            (id, name, timezone, safety_amount_paise, escalation_stake_paise,
             horizon_days, payment_days, language)
        VALUES (?, ?, 'Asia/Kolkata', ?, 5000000, 14, 'MON,THU', 'en')
        """,
        (BUSINESS_ID, "Saraswati Precision Works", 25_000_000),  # ₹2,50,000 safety
    )

    conn.execute(
        """
        INSERT INTO bank_account
            (id, business_id, bank_name, account_name, account_mask,
             opening_balance_paise, opening_balance_at, status)
        VALUES (1, ?, 'HDFC Bank', 'Current Account', 'XXXX4821', ?, '2026-10-12', 'active')
        """,
        (BUSINESS_ID, 62_000_000),  # ₹6,20,000 observed cash, Mon 12 Oct 2026
    )

    parties = [
        # id, kind, name
        (1, "vendor", "Ashirwad Paper Suppliers"),
        (2, "vendor", "City Electricity Board"),
        (3, "vendor", "Prime Chem Industries"),
        (4, "customer", "Kaveri Traders"),
        (5, "customer", "Nandi Foods"),
    ]
    conn.executemany(
        "INSERT INTO party (id, business_id, kind, name) VALUES (?, ?, ?, ?)",
        [(pid, BUSINESS_ID, kind, name) for pid, kind, name in parties],
    )

    # Payables (TDD Part 1, "Worked example" table). All CONFIRMED: ready for
    # the planner (CHG-003) to turn into PLANNED/ESCALATE. No bill this
    # fortnight is flexible, so grace_days is 0 throughout.
    payables = [
        # party_id, invoice_number, amount_paise, due_date, priority
        (1, "PAPER-001", 18_000_000, "2026-10-14", "normal"),
        (None, "PFESI-OCT26", 4_500_000, "2026-10-15", "statutory"),  # ESTIMATED by the CA
        (2, "ELEC-OCT26", 3_500_000, "2026-10-16", "critical"),
        (None, "GST-OCT26", 9_000_000, "2026-10-20", "statutory"),  # CONFIRMED by the CA
        (3, "PRIME-001", 12_000_000, "2026-10-22", "normal"),
    ]
    conn.executemany(
        """
        INSERT INTO payable
            (business_id, party_id, invoice_number, amount_paise, due_date,
             priority, grace_days, status)
        VALUES (?, ?, ?, ?, ?, ?, 0, 'CONFIRMED')
        """,
        [
            (BUSINESS_ID, party_id, inv, amount, due, priority)
            for party_id, inv, amount, due, priority in payables
        ],
    )

    # Receivables. Kaveri is COMMITTED (counted in the forecast); Nandi is
    # EXPECTED and outside the 14-day horizon, so the planner won't count it
    # until the owner negotiates it earlier (the worked example's shortfall
    # option).
    receivables = [
        (4, "KAVERI-001", 3_300_000, "2026-10-13", "COMMITTED"),
        (5, "NANDI-001", 20_000_000, "2026-10-28", "EXPECTED"),
    ]
    conn.executemany(
        """
        INSERT INTO receivable
            (business_id, party_id, invoice_number, amount_paise, expected_date, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (BUSINESS_ID, party_id, inv, amount, expected, confidence)
            for party_id, inv, amount, expected, confidence in receivables
        ],
    )

    conn.commit()


def main() -> None:
    db_path = os.environ.get("DATABASE_PATH", "./data/cashflow.db")
    apply_migrations(db_path)  # idempotent; seed.py can run standalone
    conn = sqlite3.connect(db_path)
    try:
        seed(conn)
    finally:
        conn.close()
    print(f"seed: loaded the worked-example business into {db_path}")


if __name__ == "__main__":
    main()
