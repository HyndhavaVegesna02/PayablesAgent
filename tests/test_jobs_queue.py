import sqlite3
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.clock import FakeClock
from app.db.migrate import apply_migrations
from app.jobs.queue import claim_one, enqueue, mark_done, mark_failed


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    apply_migrations(path)
    return path


def _connect(db_path):
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def test_enqueue_then_claim_returns_the_job(db_path):
    conn = _connect(db_path)
    job_id = enqueue(conn, kind="poll_mail", payload={}, run_after="2026-01-01T00:00:00")
    conn.commit()

    claimed = claim_one(conn)
    conn.commit()

    assert claimed is not None
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"


def test_claim_one_skips_jobs_not_yet_due(db_path):
    conn = _connect(db_path)
    enqueue(conn, kind="poll_mail", payload={}, run_after="2099-01-01T00:00:00")
    conn.commit()

    claimed = claim_one(conn, now="2026-01-01T00:00:00")
    assert claimed is None


def test_enqueue_is_idempotent_on_idempotency_key(db_path):
    conn = _connect(db_path)
    first = enqueue(
        conn, kind="process_document", payload={"id": 1},
        run_after="2026-01-01T00:00:00", idempotency_key="doc:1",
    )
    conn.commit()
    second = enqueue(
        conn, kind="process_document", payload={"id": 1},
        run_after="2026-01-01T00:00:00", idempotency_key="doc:1",
    )
    conn.commit()

    assert first == second
    count = conn.execute("SELECT COUNT(*) FROM job").fetchone()[0]
    assert count == 1


def test_mark_done_and_mark_failed_update_status(db_path):
    conn = _connect(db_path)
    job_id = enqueue(conn, kind="replan", payload={}, run_after="2026-01-01T00:00:00")
    conn.commit()
    claim_one(conn)
    conn.commit()

    mark_done(conn, job_id)
    conn.commit()
    row = conn.execute("SELECT status FROM job WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "done"

    job_id2 = enqueue(conn, kind="replan", payload={}, run_after="2026-01-01T00:00:00")
    conn.commit()
    claim_one(conn)
    conn.commit()
    mark_failed(conn, job_id2, "boom")
    conn.commit()
    row2 = conn.execute(
        "SELECT status, attempts, last_error FROM job WHERE id = ?", (job_id2,)
    ).fetchone()
    assert row2["status"] == "queued"  # retried, not dead yet
    assert row2["attempts"] == 1
    assert row2["last_error"] == "boom"


def test_enqueue_default_run_after_comes_from_the_injected_clock(db_path):
    conn = _connect(db_path)
    fake = FakeClock(datetime(2026, 3, 1, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")))

    job_id = enqueue(conn, kind="poll_mail", payload={}, clock=fake)
    conn.commit()

    row = conn.execute("SELECT run_after FROM job WHERE id = ?", (job_id,)).fetchone()
    assert row["run_after"] == fake.now().isoformat()


def test_claim_one_default_now_comes_from_the_injected_clock(db_path):
    conn = _connect(db_path)
    enqueue(conn, kind="poll_mail", payload={}, run_after="2026-01-01T00:00:00+05:30")
    conn.commit()

    before = FakeClock(datetime(2025, 1, 1, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert claim_one(conn, clock=before) is None  # not due yet, per this fake "now"

    after = FakeClock(datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    claimed = claim_one(conn, clock=after)  # same job, now due per this fake "now"
    assert claimed is not None


def test_mark_failed_marks_dead_once_max_attempts_reached(db_path):
    conn = _connect(db_path)
    job_id = enqueue(
        conn, kind="poll_mail", payload={}, run_after="2026-01-01T00:00:00", max_attempts=2,
    )
    conn.commit()

    claim_one(conn)
    conn.commit()
    mark_failed(conn, job_id, "first failure")
    conn.commit()
    row = conn.execute("SELECT status, attempts FROM job WHERE id = ?", (job_id,)).fetchone()
    assert (row["status"], row["attempts"]) == ("queued", 1)

    claim_one(conn)
    conn.commit()
    mark_failed(conn, job_id, "second failure")
    conn.commit()
    row2 = conn.execute(
        "SELECT status, attempts, last_error FROM job WHERE id = ?", (job_id,)
    ).fetchone()
    assert (row2["status"], row2["attempts"], row2["last_error"]) == ("dead", 2, "second failure")


def test_two_concurrent_claims_on_one_job_only_one_succeeds(db_path):
    conn = _connect(db_path)
    job_id = enqueue(conn, kind="poll_mail", payload={}, run_after="2026-01-01T00:00:00")
    conn.commit()

    results: list = []

    def worker():
        c = _connect(db_path)
        try:
            claimed = claim_one(c)
            c.commit()
            results.append(claimed)
        finally:
            c.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [r for r in results if r is not None]
    assert len(successes) == 1
    assert successes[0]["id"] == job_id
