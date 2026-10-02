"""SQLite-backed job table (TDD Part 2, "Jobs and the document pipeline").
All background work is a row here, so nothing is lost if the worker stops.
The worker claims one job at a time with UPDATE ... RETURNING; two claims
racing for the same row never both succeed.

Callers must set `conn.row_factory = sqlite3.Row` before using this module —
mark_failed and claim_one's return value both rely on column-name access."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def enqueue(
    conn: sqlite3.Connection,
    *,
    kind: str,
    payload: dict[str, Any],
    run_after: str | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 5,
) -> int:
    run_after = run_after or _utcnow_iso()
    cur = conn.execute(
        """
        INSERT INTO job (kind, payload_json, idempotency_key, status, run_after, max_attempts)
        VALUES (?, ?, ?, 'queued', ?, ?)
        ON CONFLICT(idempotency_key) DO NOTHING
        """,
        (kind, json.dumps(payload), idempotency_key, run_after, max_attempts),
    )
    if cur.rowcount == 0 and idempotency_key is not None:
        row = conn.execute(
            "SELECT id FROM job WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return row["id"] if isinstance(row, sqlite3.Row) else row[0]
    return cur.lastrowid


def claim_one(
    conn: sqlite3.Connection,
    kinds: list[str] | None = None,
    now: str | None = None,
) -> sqlite3.Row | None:
    now = now or _utcnow_iso()
    kind_filter = ""
    kind_params: list[str] = []
    if kinds:
        kind_filter = f"AND kind IN ({','.join('?' for _ in kinds)})"
        kind_params = list(kinds)

    cur = conn.execute(
        f"""
        UPDATE job SET status = 'running', locked_at = ?
        WHERE id = (
            SELECT id FROM job
            WHERE status = 'queued' AND run_after <= ?
            {kind_filter}
            ORDER BY id
            LIMIT 1
        )
        RETURNING *
        """,
        [now, now, *kind_params],
    )
    row = cur.fetchone()
    return row


def mark_done(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("UPDATE job SET status = 'done' WHERE id = ?", (job_id,))


def mark_failed(
    conn: sqlite3.Connection,
    job_id: int,
    error: str,
    retry_at: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT attempts, max_attempts, run_after FROM job WHERE id = ?", (job_id,)
    ).fetchone()
    attempts = row["attempts"] + 1
    dead = attempts >= row["max_attempts"]
    conn.execute(
        """
        UPDATE job
        SET attempts = ?, last_error = ?, status = ?, run_after = ?
        WHERE id = ?
        """,
        (
            attempts,
            error,
            "dead" if dead else "queued",
            retry_at if retry_at is not None else row["run_after"],
            job_id,
        ),
    )
