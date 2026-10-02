"""Read-only database access. Used by the agent's get_ledger tool so it cannot
write to the ledger even if the rest of the agent code is wrong (TDD Part 2,
"Security in code")."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def read_only_connection(db_path: str | Path) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
