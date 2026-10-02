"""Batch-0 review (major): schema.sql's `PRAGMA foreign_keys = ON` only ever
ran on migrate.py's own one-off connection during migration -- SQLite does
not persist that pragma in the database file, so every other connection
(seed.py's writes, main.py's health check, any future write path) silently
ran with FK enforcement off. app/db/connection.py::write_connection() is the
one place that sets it, so every writer goes through it."""

import sqlite3

import pytest

from app.db.connection import write_connection
from app.db.migrate import apply_migrations


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "fk-test.db"
    apply_migrations(path)
    return path


def test_write_connection_enforces_foreign_keys(db_path):
    conn = write_connection(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "INSERT INTO app_user (business_id, email, role, password_hash) "
                "VALUES (999, 'orphan@example.com', 'owner', 'hash')"
            )
    finally:
        conn.close()


def test_write_connection_sets_row_factory_to_row(db_path):
    conn = write_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM business").fetchone()
        assert row["n"] == 0  # column-name access requires sqlite3.Row
    finally:
        conn.close()


def test_a_plain_sqlite3_connect_does_not_enforce_foreign_keys(db_path):
    # Documents the exact gap write_connection closes: without it, the same
    # insert above is silently allowed, because PRAGMA foreign_keys=ON from
    # schema.sql does not persist across connections.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO app_user (business_id, email, role, password_hash) "
            "VALUES (999, 'orphan@example.com', 'owner', 'hash')"
        )
        conn.rollback()  # don't leave the orphan row behind
    finally:
        conn.close()
