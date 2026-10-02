"""FastAPI app factory (TDD Part 2, "At a glance"). The web process never
calls Gemini; in this phase it exposes only GET /api/health."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI

from app.config import Settings
from app.db.read import read_only_connection


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="PayablesAgent")
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict:
        db_path = Path(settings.database_path)
        database = {"path": str(db_path), "reachable": False}
        queue_depth = None

        if db_path.exists():
            try:
                conn = read_only_connection(db_path)
                try:
                    conn.execute("SELECT 1")
                    database["reachable"] = True
                    queue_depth = conn.execute(
                        "SELECT COUNT(*) FROM job WHERE status = 'queued'"
                    ).fetchone()[0]
                finally:
                    conn.close()
            except sqlite3.Error:
                database["reachable"] = False

        return {
            "status": "ok" if database["reachable"] else "degraded",
            "database": database,
            "queue_depth": queue_depth,
            # The worker process (job runner, scheduler) lands in later phases.
            "worker": "not yet implemented",
        }

    return app


app = create_app()
