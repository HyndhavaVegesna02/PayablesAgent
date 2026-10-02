"""Loads the worked-example business from TDD Part 1, "Worked example".
Every figure here reconciles (it doubles as the planner's golden test seed),
so changing a number here without re-checking that section will break the
planner golden test.

Ledger rows (payables, receivables, tax obligations) go through
app.ledger.writer, so a seeded database carries the same audit trail as one
built by the app. Because events are append-only, seeding never deletes:
it refuses a database that already has a business, and `--fresh`
(`make reseed`) recreates the database file instead.
"""

from __future__ import annotations

import argparse
import functools
import sqlite3
import sys
from datetime import date
from pathlib import Path

from app.clock import Clock, DemoClock, clock_for
from app.config import Settings
from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from app.domain.models import PayableNew, ReceivableNew, TaxObligationNew
from app.jobs.replan import replan
from app.ledger import writer
from app.ledger.writer import EntityRef
from app.web.auth import hash_password

BUSINESS_ID = 1
OWNER = "owner:1"
OWNER_EMAIL = "owner@example.test"
HELPER_EMAIL = "helper@example.test"
DEV_OWNER_PASSWORD = Settings.model_fields["seed_owner_password"].default
DEV_HELPER_PASSWORD = Settings.model_fields["seed_helper_password"].default
WHY = dict(reason="seed: TDD Part 1 worked example", source_ref="fixture:seed")


class AlreadySeeded(Exception):
    pass


def _confirm(conn: sqlite3.Connection, payable_id: int, clock: Clock | None) -> None:
    writer.transition(
        EntityRef("payable", payable_id), "CONFIRMED", OWNER, **WHY,
        conn=conn, expected_version=1, clock=clock,
    )


@functools.lru_cache(maxsize=8)
def _password_hash(password: str) -> str:
    # Cached so a test run hashes each demo password once, not once per seed.
    return hash_password(password)


def seed(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    *,
    owner_password: str = DEV_OWNER_PASSWORD,
    helper_password: str = DEV_HELPER_PASSWORD,
) -> None:
    if conn.execute("SELECT COUNT(*) FROM business").fetchone()[0]:
        raise AlreadySeeded("database already has a business; run `make reseed` to start fresh")
    kw = dict(actor=OWNER, conn=conn, clock=clock, **WHY)

    with writer.atomic(conn):
        conn.execute(
            """
            INSERT INTO business
                (id, name, timezone, safety_amount_paise, escalation_stake_paise,
                 horizon_days, payment_days, language)
            VALUES (?, ?, 'Asia/Kolkata', ?, 5000000, 14, 'MON,THU', 'en')
            """,
            (BUSINESS_ID, "Saraswati Precision Works", 25_000_000),  # ₹2,50,000 safety
        )
        # The demo logins: the owner every seeded event names, and a helper who
        # can only submit bills (Part 1, "Roles"). Passwords come from Settings
        # (SEED_OWNER_PASSWORD, SEED_HELPER_PASSWORD; dev defaults in .env.example).
        conn.executemany(
            "INSERT INTO app_user (id, business_id, email, role, password_hash) VALUES (?, ?, ?, ?, ?)",
            [
                (1, BUSINESS_ID, OWNER_EMAIL, "owner", _password_hash(owner_password)),
                (2, BUSINESS_ID, HELPER_EMAIL, "helper", _password_hash(helper_password)),
            ],
        )
        conn.execute(
            """
            INSERT INTO bank_account
                (id, business_id, bank_name, account_name, account_mask, alert_senders_json,
                 opening_balance_paise, opening_balance_at, status)
            VALUES (1, ?, 'HDFC Bank', 'Current Account', 'XXXX4821',
                    '["alerts@hdfcbank.example"]',  -- fictional sender of fixtures/test_inbox
                    ?, '2026-10-12', 'active')
            """,
            (BUSINESS_ID, 62_000_000),  # ₹6,20,000 observed cash, Mon 12 Oct 2026
        )
        conn.executemany(
            "INSERT INTO party (id, business_id, kind, name) VALUES (?, ?, ?, ?)",
            [
                (1, BUSINESS_ID, "vendor", "Ashirwad Paper Suppliers"),
                (2, BUSINESS_ID, "vendor", "City Electricity Board"),
                (3, BUSINESS_ID, "vendor", "Prime Chem Industries"),
                (4, BUSINESS_ID, "customer", "Kaveri Traders"),
                (5, BUSINESS_ID, "customer", "Nandi Foods"),
            ],
        )

        def vendor_bill(party_id: int, invoice: str, paise: int, due: date, priority: str) -> None:
            p = writer.create_payable(
                PayableNew(business_id=BUSINESS_ID, party_id=party_id, invoice_number=invoice,
                           amount_paise=paise, due_date=due, priority=priority),
                **kw,
            )
            _confirm(conn, p.id, clock)

        # Created in the worked example's row order, so payable ids stay 1..5.
        vendor_bill(1, "PAPER-001", 18_000_000, date(2026, 10, 14), "normal")

        # PF and ESI are one ₹45,000 line in the worked example. The PF ₹36,000 /
        # ESI ₹9,000 split is fixture-invented (PO-approved, batch 1 Q2): the TDD
        # gives only the combined estimate. Both obligations back one payable.
        pf = writer.create_tax_obligation(
            TaxObligationNew(business_id=BUSINESS_ID, tax_type="PF", period="2026-09",
                             due_date=date(2026, 10, 15), amount_paise=3_600_000,
                             amount_status="ESTIMATED"),
            invoice_number="PFESI-OCT26", payable_amount_paise=4_500_000, **kw,
        )
        writer.create_tax_obligation(
            TaxObligationNew(business_id=BUSINESS_ID, tax_type="ESI", period="2026-09",
                             due_date=date(2026, 10, 15), amount_paise=900_000,
                             amount_status="ESTIMATED"),
            payable_id=pf.payable_id, **kw,
        )
        _confirm(conn, pf.payable_id, clock)

        vendor_bill(2, "ELEC-OCT26", 3_500_000, date(2026, 10, 16), "critical")

        gst = writer.create_tax_obligation(
            TaxObligationNew(business_id=BUSINESS_ID, tax_type="GST", period="2026-09",
                             due_date=date(2026, 10, 20), amount_paise=9_000_000,
                             amount_status="CONFIRMED"),
            invoice_number="GST-OCT26", **kw,
        )
        _confirm(conn, gst.payable_id, clock)

        vendor_bill(3, "PRIME-001", 12_000_000, date(2026, 10, 22), "normal")  # no grace days

        # Kaveri is COMMITTED (counted in the forecast). Nandi is EXPECTED and
        # outside the 14-day horizon, so it is not counted until the owner asks
        # for it earlier (the worked example's shortfall option).
        for party_id, invoice, paise, expected, confidence in (
            (4, "KAVERI-001", 3_300_000, date(2026, 10, 13), "COMMITTED"),
            (5, "NANDI-001", 20_000_000, date(2026, 10, 28), "EXPECTED"),
        ):
            writer.create_receivable(
                ReceivableNew(business_id=BUSINESS_ID, party_id=party_id, invoice_number=invoice,
                              amount_paise=paise, expected_date=expected, confidence=confidence),
                **kw,
            )


def _remove_database(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the worked-example business.")
    parser.add_argument("--fresh", action="store_true",
                        help="delete the database file first, then migrate and seed")
    args = parser.parse_args(argv)
    # The same setting the app and worker read (.env or the environment), so
    # `make reseed` replaces the database `make run` actually uses.
    settings = Settings()
    db_path = Path(settings.database_path)

    clock = clock_for(settings.demo_now, settings.data_dir)
    if args.fresh:
        if isinstance(clock, DemoClock):
            clock.reset()  # a fresh demo starts again at DEMO_NOW
        try:
            _remove_database(db_path)
        except PermissionError:
            print(
                f"seed: cannot delete {db_path}: another process has it open. "
                "Stop `make run` and `make worker`, then run `make reseed` again.",
                file=sys.stderr,
            )
            return 1
    apply_migrations(db_path)  # idempotent; seed.py can run standalone
    conn = write_connection(db_path)
    try:
        seed(conn, clock, owner_password=settings.seed_owner_password,
             helper_password=settings.seed_helper_password)
        # The first plan, so the app has one to show before the worker's Monday
        # plan runs. It is the replan job's own function, as the planner.
        replan(conn, BUSINESS_ID, triggered_by="seed", clock=clock)
    except AlreadySeeded:
        print(f"seed: {db_path} is already seeded; run `make reseed` to start fresh")
        return 0
    finally:
        conn.close()
    print(f"seed: loaded the worked-example business into {db_path}, planned from {clock.today()}")
    print(f"seed: log in as {OWNER_EMAIL} (SEED_OWNER_PASSWORD) or {HELPER_EMAIL} (SEED_HELPER_PASSWORD); "
          "the dev defaults are in .env.example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
