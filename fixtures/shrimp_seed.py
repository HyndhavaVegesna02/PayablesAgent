"""Loads the shrimp-farm demo profile (CHG-058; dev only, R011): Godavari
Aqua Farm, a vannamei farmer in coastal Andhra Pradesh, on Mon 19 Oct 2026,
the start of the crop's last fortnight (final harvest and settlement). The
business, its people and every figure are fictional.

Like fixtures/seed.py (whose helpers it shares and which it leaves alone),
ledger rows go through app.ledger.writer and seeding never deletes. It only
ever writes ./data/shrimp.db and ./data/shrimp-files: `make reseed-shrimp`
sets those paths, and any other DATABASE_PATH or DATA_DIR is refused, so it
can never replace the worked example's database or reset its demo clock."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

from app.clock import Clock, DemoClock, clock_for
from app.config import Settings
from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from app.domain.models import PayableNew, ReceivableNew
from app.jobs.replan import replan
from app.ledger import writer
from app.ledger.writer import EntityRef
from fixtures.seed import (
    BUSINESS_ID,
    DEV_HELPER_PASSWORD,
    DEV_OWNER_PASSWORD,
    HELPER_EMAIL,
    OWNER,
    OWNER_EMAIL,
    AlreadySeeded,
    _password_hash,
    _remove_database,
)

ROOT = Path(__file__).resolve().parent.parent
SHRIMP_DB = ROOT / "data" / "shrimp.db"
SHRIMP_FILES = ROOT / "data" / "shrimp-files"  # its documents and its demo clock
WHY = dict(reason="seed: the shrimp-farm demo profile (CHG-058)", source_ref="fixture:shrimp_seed")

DEALER, AGENT, LANDOWNER, POWER, CARETAKER = 1, 2, 3, 4, 5
DEALER_GSTIN = "37ZZZSZ0007Z1ZW"  # fictional; a valid GSTIN check character (app/validate/gstin.py)
DEALER_BANK = ("XXXX2201", "SBIN0004321")  # verified on record before the fortnight (fictional)


def seed(conn: sqlite3.Connection, clock: Clock | None = None, *, owner_password: str = DEV_OWNER_PASSWORD,
         helper_password: str = DEV_HELPER_PASSWORD) -> None:
    if not owner_password.strip() or not helper_password.strip():
        raise ValueError("SEED_OWNER_PASSWORD and SEED_HELPER_PASSWORD must not be blank")
    if conn.execute("SELECT COUNT(*) FROM business").fetchone()[0]:
        raise AlreadySeeded("database already has a business; run `make reseed-shrimp` to start fresh")
    kw = dict(actor=OWNER, conn=conn, clock=clock, **WHY)

    with writer.atomic(conn):
        conn.execute(
            "INSERT INTO business (id, name, timezone, safety_amount_paise, escalation_stake_paise, horizon_days, "
            "payment_days, language) VALUES (?, ?, 'Asia/Kolkata', ?, 5000000, 14, 'MON,THU', 'en')",
            (BUSINESS_ID, "Godavari Aqua Farm", 5_000_000),  # ₹50,000 safety
        )
        conn.executemany(
            "INSERT INTO app_user (id, business_id, email, role, password_hash) VALUES (?, ?, ?, ?, ?)",
            [(1, BUSINESS_ID, OWNER_EMAIL, "owner", _password_hash(owner_password)),
             (2, BUSINESS_ID, HELPER_EMAIL, "helper", _password_hash(helper_password))],
        )
        conn.execute(
            "INSERT INTO bank_account (id, business_id, bank_name, account_name, account_mask, alert_senders_json, "
            "opening_balance_paise, opening_balance_at, status) VALUES (1, ?, 'HDFC Bank', 'Current Account', "
            "'XXXX7310', '[\"alerts@hdfcbank.example\"]', ?, '2026-10-19', 'active')",
            (BUSINESS_ID, 11_000_000),  # ₹1,10,000 on Mon 19 Oct
        )
        conn.executemany(
            "INSERT INTO party (id, business_id, kind, name, gstin, bank_account_mask, bank_ifsc, bank_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(DEALER, BUSINESS_ID, "vendor", "Sri Lakshmi Aqua Feeds", DEALER_GSTIN, *DEALER_BANK, "verified"),
             (AGENT, BUSINESS_ID, "customer", "Ravi Traders", None, None, None, "none"),
             (LANDOWNER, BUSINESS_ID, "vendor", "K. Subba Rao", None, None, None, "none"),
             (POWER, BUSINESS_ID, "vendor", "APSPDCL", None, None, None, "none"),
             (CARETAKER, BUSINESS_ID, "vendor", "Lakshman (caretaker)", None, None, None, "none")],
        )
        for party_id, invoice, paise, due, priority in (
            (LANDOWNER, "LEASE-OCT26", 7_500_000, date(2026, 10, 31), "flexible"),  # due after the harvest
            (POWER, "APSPDCL-OCT26", 1_500_000, date(2026, 10, 22), "critical"),  # the aerators run on it
            (CARETAKER, "WAGES-OCT26", 1_500_000, date(2026, 10, 23), "critical"),
        ):
            p = writer.create_payable(PayableNew(business_id=BUSINESS_ID, party_id=party_id, invoice_number=invoice,
                                                 amount_paise=paise, due_date=due, priority=priority), **kw)
            writer.transition(EntityRef("payable", p.id), "CONFIRMED", OWNER, **WHY, conn=conn, expected_version=1,
                              clock=clock)
        # The advance is promised for harvest day (COMMITTED, counted). The balance is EXPECTED: not counted
        # until it lands or the owner asks for it early, like Nandi Foods in the worked example.
        for invoice, paise, expected, confidence in (
            ("HARVEST-ADV", 20_000_000, date(2026, 10, 20), "COMMITTED"),
            ("HARVEST-BAL", 101_500_000, date(2026, 10, 30), "EXPECTED"),
        ):
            writer.create_receivable(ReceivableNew(business_id=BUSINESS_ID, party_id=AGENT, invoice_number=invoice,
                                                   amount_paise=paise, expected_date=expected,
                                                   confidence=confidence), **kw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the shrimp-farm demo profile into ./data/shrimp.db.")
    parser.add_argument("--fresh", action="store_true", help="delete ./data/shrimp.db first, then migrate and seed")
    args = parser.parse_args(argv)
    settings = Settings()
    db_path = Path(settings.database_path)
    if db_path.resolve() != SHRIMP_DB:
        print(f"shrimp seed: refusing DATABASE_PATH={settings.database_path}: this profile only writes "
              "./data/shrimp.db (run `make reseed-shrimp`)", file=sys.stderr)
        return 2
    if Path(settings.data_dir).resolve() != SHRIMP_FILES:
        print(f"shrimp seed: refusing DATA_DIR={settings.data_dir}: this profile's documents and demo clock live in "
              "./data/shrimp-files (run `make reseed-shrimp`)", file=sys.stderr)
        return 2
    clock = clock_for(settings.demo_now, settings.data_dir)
    if not isinstance(clock, DemoClock):
        print("shrimp seed: the profile is a demo: set DEMO_NOW (.env.shrimp does)", file=sys.stderr)
        return 2
    if args.fresh:
        clock.reset()  # a fresh demo starts again at DEMO_NOW
        try:
            _remove_database(db_path)
        except PermissionError:
            print(f"shrimp seed: cannot delete {db_path}: another process has it open. Stop `make run-shrimp` "
                  "and `make worker-shrimp`, then run `make reseed-shrimp` again.", file=sys.stderr)
            return 1
    db_path.parent.mkdir(parents=True, exist_ok=True)
    apply_migrations(db_path)
    conn = write_connection(db_path)
    try:
        seed(conn, clock, owner_password=settings.seed_owner_password, helper_password=settings.seed_helper_password)
        replan(conn, BUSINESS_ID, triggered_by="seed", clock=clock)
    except AlreadySeeded:
        print(f"shrimp seed: {db_path} is already seeded; run `make reseed-shrimp` to start fresh")
        return 0
    finally:
        conn.close()
    print(f"shrimp seed: loaded Godavari Aqua Farm into {db_path}, planned from {clock.today()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
