import json
from collections import Counter

import pytest

from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from fixtures import seed as seed_module
from fixtures.seed import AlreadySeeded, seed


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "seed-test.db"
    apply_migrations(db_path)
    c = write_connection(db_path)  # exercises seed() under real FK enforcement
    seed(c)
    yield c
    c.close()


def test_seed_creates_worked_example_business(conn):
    business = conn.execute("SELECT * FROM business WHERE id = 1").fetchone()
    assert business["safety_amount_paise"] == 25_000_000  # ₹2,50,000
    assert business["payment_days"] == "MON,THU"
    assert business["horizon_days"] == 14


def test_seed_creates_the_owner_and_a_helper_with_real_demo_logins(conn):
    from argon2 import PasswordHasher

    users = {r["id"]: r for r in conn.execute("SELECT * FROM app_user")}
    assert (users[1]["role"], users[1]["email"], users[1]["business_id"]) == ("owner", "owner@example.test", 1)
    assert (users[2]["role"], users[2]["email"], users[2]["business_id"]) == ("helper", "helper@example.test", 1)
    hasher = PasswordHasher()
    assert hasher.verify(users[1]["password_hash"], "owner-demo-pass")  # dev defaults (.env.example)
    assert hasher.verify(users[2]["password_hash"], "helper-demo-pass")
    assert users[1]["password_hash"].startswith("$argon2id$")


def test_the_seed_takes_its_passwords_from_settings_and_never_prints_them(tmp_path, monkeypatch, capsys):
    from argon2 import PasswordHasher

    db_path = tmp_path / "pw.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("SEED_OWNER_PASSWORD", "s3cret-owner-pw")
    monkeypatch.setenv("SEED_HELPER_PASSWORD", "s3cret-helper-pw")
    assert seed_module.main([]) == 0
    out = capsys.readouterr().out
    assert "owner@example.test" in out and "helper@example.test" in out
    assert "s3cret" not in out
    c = write_connection(db_path)
    hashes = dict(c.execute("SELECT email, password_hash FROM app_user").fetchall())
    c.close()
    assert PasswordHasher().verify(hashes["owner@example.test"], "s3cret-owner-pw")


def test_seed_creates_the_bank_account_with_observed_cash(conn):
    row = conn.execute(
        "SELECT calculated_balance_paise FROM account_balance ab "
        "JOIN bank_account a ON a.id = ab.account_id WHERE a.business_id = 1"
    ).fetchone()
    assert row["calculated_balance_paise"] == 62_000_000  # ₹6,20,000, no txns yet


def test_seed_creates_five_payables_matching_the_worked_example(conn):
    payables = {
        row["invoice_number"]: (row["id"], row["amount_paise"], row["due_date"], row["priority"])
        for row in conn.execute("SELECT * FROM payable WHERE business_id = 1").fetchall()
    }
    assert payables == {
        "PAPER-001": (1, 18_000_000, "2026-10-14", "normal"),
        "PFESI-OCT26": (2, 4_500_000, "2026-10-15", "statutory"),
        "ELEC-OCT26": (3, 3_500_000, "2026-10-16", "critical"),
        "GST-OCT26": (4, 9_000_000, "2026-10-20", "statutory"),
        "PRIME-001": (5, 12_000_000, "2026-10-22", "normal"),
    }
    prime = conn.execute("SELECT grace_days FROM payable WHERE invoice_number = 'PRIME-001'").fetchone()
    assert prime["grace_days"] == 0  # TDD: "no grace days"
    rows = conn.execute("SELECT status, version FROM payable").fetchall()
    assert {(r["status"], r["version"]) for r in rows} == {("CONFIRMED", 2)}


def test_seed_creates_two_receivables_with_correct_confidence(conn):
    receivables = {
        row["invoice_number"]: (row["amount_paise"], row["expected_date"], row["confidence"])
        for row in conn.execute("SELECT * FROM receivable WHERE business_id = 1").fetchall()
    }
    assert receivables == {
        "KAVERI-001": (3_300_000, "2026-10-13", "COMMITTED"),
        "NANDI-001": (20_000_000, "2026-10-28", "EXPECTED"),
    }


def test_seed_links_tax_obligations_to_their_statutory_payables(conn):
    rows = conn.execute(
        "SELECT t.tax_type, t.amount_paise, t.amount_status, t.period, p.invoice_number "
        "FROM tax_obligation t JOIN payable p ON p.id = t.payable_id ORDER BY t.tax_type"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("ESI", 900_000, "ESTIMATED", "2026-09", "PFESI-OCT26"),
        ("GST", 9_000_000, "CONFIRMED", "2026-09", "GST-OCT26"),
        ("PF", 3_600_000, "ESTIMATED", "2026-09", "PFESI-OCT26"),
    ]


def test_every_ledger_row_has_its_audit_trail(conn):
    evs = conn.execute("SELECT * FROM event").fetchall()
    assert Counter((e["entity"], e["event_type"]) for e in evs) == {
        ("payable", "PAYABLE_CREATED"): 5,
        ("payable", "PAYABLE_CONFIRMED"): 5,
        ("receivable", "RECEIVABLE_CREATED"): 2,
        ("tax_obligation", "TAX_OBLIGATION_CREATED"): 3,
    }
    assert {e["actor"] for e in evs} == {"owner:1"}
    assert {e["reason"] for e in evs} == {"seed: TDD Part 1 worked example"}
    assert {e["source_ref"] for e in evs} == {"fixture:seed"}
    for table in ("payable", "receivable", "tax_obligation"):
        ids = {r[0] for r in conn.execute(f"SELECT id FROM {table}")}
        created = {e["entity_id"] for e in evs if e["event_type"] == f"{table.upper()}_CREATED"}
        assert ids == created, table


def test_seeding_twice_refuses_and_changes_nothing(conn):
    events_before = conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    with pytest.raises(AlreadySeeded):
        seed(conn)
    assert conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == events_before
    assert conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 5


def _counts(db_path):
    c = write_connection(db_path)
    try:
        return {
            t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("business", "payable", "receivable", "tax_obligation", "event")
        }
    finally:
        c.close()


def test_make_seed_is_a_harmless_no_op_the_second_time(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    assert seed_module.main([]) == 0
    first = _counts(db_path)
    assert seed_module.main([]) == 0
    assert "already seeded" in capsys.readouterr().out
    assert _counts(db_path) == first


def test_fresh_recreates_the_file_instead_of_deleting_rows(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DEMO_NOW", "2026-10-12T09:00:00+05:30")
    assert seed_module.main([]) == 0
    first = _counts(db_path)
    marker = write_connection(db_path)  # a row only the old file has
    marker.execute("INSERT INTO party (business_id, kind, name) VALUES (1, 'vendor', 'MARKER')")
    marker.commit()
    marker.close()
    capsys.readouterr()

    assert seed_module.main(["--fresh"]) == 0

    assert "loaded the worked-example business" in capsys.readouterr().out
    check = write_connection(db_path)
    assert check.execute("SELECT COUNT(*) FROM party WHERE name = 'MARKER'").fetchone()[0] == 0
    check.close()
    # 15 seeded rows' events, plus the first plan's four PAY lines moving to PLANNED.
    assert _counts(db_path) == first == {
        "business": 1, "payable": 5, "receivable": 2, "tax_obligation": 3, "event": 19,
    }


def test_the_seed_makes_the_first_plan_at_demo_now(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "plan.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DEMO_NOW", "2026-10-12T09:00:00+05:30")
    assert seed_module.main([]) == 0
    assert "planned from 2026-10-12" in capsys.readouterr().out
    c = write_connection(db_path)
    run = c.execute("SELECT * FROM plan_run WHERE is_current = 1").fetchone()
    events = c.execute("SELECT DISTINCT occurred_at FROM event").fetchall()
    c.close()
    assert (run["triggered_by"], run["lowest_balance_paise"], run["lowest_on"]) == ("seed", 18_300_000, "2026-10-22")
    assert [e[0] for e in events] == ["2026-10-12T09:00:00+05:30"]


def test_demo_now_needs_an_offset(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="UTC offset"):
        Settings(_env_file=None, demo_now="2026-10-12T09:00:00")
    assert Settings(_env_file=None, demo_now="").demo_now == ""


def test_the_seed_reads_database_path_through_settings_like_the_app(tmp_path, monkeypatch, capsys):
    # A DATABASE_PATH only in a .env file: the app (Settings) uses it, so the seed must too.
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_PATH=./from-dotenv.db\n", encoding="utf-8")
    assert seed_module.main([]) == 0
    assert (tmp_path / "from-dotenv.db").exists()
    assert not (tmp_path / "data" / "cashflow.db").exists()


def test_fresh_on_a_database_another_process_holds_exits_with_a_clear_message(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    assert seed_module.main([]) == 0
    capsys.readouterr()

    def locked(self, missing_ok=False):
        raise PermissionError(32, "The process cannot access the file", str(self))

    monkeypatch.setattr(seed_module.Path, "unlink", locked)  # what Windows does to an open file
    assert seed_module.main(["--fresh"]) == 1
    err = capsys.readouterr().err
    assert "another process has it open" in err
    assert "make reseed" in err


def test_the_seeded_account_takes_alerts_from_the_test_inbox_sender(conn):
    row = conn.execute("SELECT alert_senders_json FROM bank_account WHERE id = 1").fetchone()
    assert json.loads(row[0]) == ["alerts@hdfcbank.example"]  # fictional; fixtures/test_inbox
