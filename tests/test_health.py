from fastapi.testclient import TestClient

from app.config import Settings
from app.db.migrate import apply_migrations
from app.jobs.queue import enqueue
from app.main import create_app


def _client(db_path) -> TestClient:
    settings = Settings(_env_file=None, database_path=str(db_path))
    return TestClient(create_app(settings))


def test_health_reports_ok_and_zero_queue_depth_on_fresh_db(tmp_path):
    db_path = tmp_path / "health.db"
    apply_migrations(db_path)

    resp = _client(db_path).get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"]["reachable"] is True
    assert body["queue_depth"] == 0
    assert body["worker"] == "not yet implemented"


def test_health_reports_queue_depth(tmp_path):
    db_path = tmp_path / "health.db"
    apply_migrations(db_path)

    import sqlite3

    conn = sqlite3.connect(db_path)
    enqueue(conn, kind="poll_mail", payload={}, run_after="2026-01-01T00:00:00")
    conn.commit()
    conn.close()

    resp = _client(db_path).get("/api/health")
    assert resp.json()["queue_depth"] == 1


def test_health_reports_degraded_when_db_missing(tmp_path):
    missing = tmp_path / "does-not-exist.db"
    resp = _client(missing).get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"]["reachable"] is False
