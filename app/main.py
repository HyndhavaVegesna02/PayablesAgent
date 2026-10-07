"""FastAPI app factory (TDD Part 2, "At a glance"). The web process never
calls Gemini (import-linter: web never imports ai). It serves the owner web
app (app/web) and GET /api/health.

`make run` starts it with `uvicorn --factory app.main:create_app`, so nothing
reads Settings when this module is imported."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI

from app.clock import Clock, clock_for
from app.config import AppConfig, Settings, load_app_config
from app.db.read import read_only_connection
from app.web.auth import check_secret
from app.worker import read_heartbeat


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    app_config: AppConfig | None = None,
) -> FastAPI:
    settings = settings or Settings()
    check_secret(settings.session_secret)  # refuses to start without one
    app = FastAPI(title="PayablesAgent", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.clock = clock or clock_for(settings.demo_now, settings.data_dir)
    app.state.app_config = app_config or load_app_config(settings.app_config_path)

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
            # The worker writes this file on every loop (batch 2 plan, Q1).
            "worker": {"last_heartbeat": read_heartbeat(settings)},
        }

    from app.web.app import install

    install(app)
    return app
