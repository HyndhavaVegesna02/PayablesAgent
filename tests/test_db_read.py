import sqlite3

import pytest

from app.db.migrate import apply_migrations
from app.db.read import read_only_connection


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    apply_migrations(path)
    return path


def test_read_only_connection_can_select(db_path):
    conn = read_only_connection(db_path)
    try:
        rows = [tuple(row) for row in conn.execute("SELECT COUNT(*) FROM business").fetchall()]
        assert rows == [(0,)]
    finally:
        conn.close()


def test_read_only_connection_cannot_write(db_path):
    conn = read_only_connection(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(
                "INSERT INTO business (id, name, safety_amount_paise) VALUES (1, 'x', 0)"
            )
    finally:
        conn.close()
