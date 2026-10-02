from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.db.migrate import apply_migrations
from app.db.read import read_only_connection


def test_health_opens_the_database_through_read_only_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    apply_migrations(db_path)
    calls = []

    def spy(path):
        calls.append(path)
        return read_only_connection(path)

    monkeypatch.setattr(main_module, "read_only_connection", spy)
    settings = Settings(_env_file=None, database_path=str(db_path))

    resp = TestClient(main_module.create_app(settings)).get("/api/health")

    assert resp.json()["database"]["reachable"] is True
    assert len(calls) == 1
