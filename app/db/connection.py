"""The one place that opens a writable connection with the pragmas the
schema actually needs enforced.

SQLite does not persist `PRAGMA foreign_keys = ON` in the database file --
it's a per-connection setting. schema.sql sets it during migration, but that
only covers migrate.py's own connection; every other connection a caller
opened with a bare sqlite3.connect() silently ran with FK enforcement off
(found in batch-0 review: an orphan app_user row with a nonexistent
business_id inserted without error). Every writer should open through this
function instead of calling sqlite3.connect() directly."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def write_connection(db_path: str | Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """`check_same_thread=False` is for the web app, whose one connection per
    request may pass between FastAPI's threadpool and its event loop, though
    never to two threads at once."""
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
