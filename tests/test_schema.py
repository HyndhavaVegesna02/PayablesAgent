import sqlite3

import pytest

from app.db.migrate import apply_migrations

EXPECTED_TABLES = {
    "business", "app_user", "party", "bank_account", "source_document",
    "candidate", "bank_txn", "payable", "receivable", "tax_obligation",
    "plan_run", "plan_line", "plan_day", "shortfall_option", "agent_case",
    "owner_question", "job", "gmail_connection", "sync_state", "event",
}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


def test_apply_migrations_creates_every_table_and_the_balance_view(db_path):
    apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        views = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()
        }
        assert EXPECTED_TABLES <= tables
        assert "account_balance" in views
    finally:
        conn.close()


def test_apply_migrations_is_idempotent(db_path):
    apply_migrations(db_path)
    apply_migrations(db_path)  # must not raise or re-apply 0001_init.sql

    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='business'"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_event_table_is_append_only(db_path):
    apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO business (id, name, safety_amount_paise) VALUES (1, 'Test', 250000)"
        )
        conn.execute(
            """
            INSERT INTO event (id, business_id, occurred_at, actor, event_type, entity, entity_id)
            VALUES (1, 1, '2026-10-12T00:00:00', 'owner:1', 'TEST', 'payable', 1)
            """
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE event SET reason = 'edited' WHERE id = 1")

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM event WHERE id = 1")
    finally:
        conn.close()


def test_schema_sql_is_regenerated_from_applied_migrations(db_path):
    apply_migrations(db_path)

    from app.db.migrate import SCHEMA_SQL_PATH

    content = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    assert "CREATE TABLE business" in content
    assert "CREATE VIEW account_balance" in content
