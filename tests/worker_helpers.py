"""A seeded worked-example database plus the settings, config and clock the
worker needs, for worker, replan and pipeline tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.clock import FakeClock
from app.config import AppConfig, Settings, load_app_config
from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from fixtures.seed import seed
from tests.ledger_helpers import fake_clock

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Env:
    conn: object
    clock: FakeClock
    settings: Settings
    app_config: AppConfig


def make_env(tmp_path: Path, *, seeded: bool = True) -> Env:
    db_path = tmp_path / "worker.db"
    apply_migrations(db_path)
    conn = write_connection(db_path)
    clock = fake_clock()
    if seeded:
        seed(conn, clock)
    settings = Settings(
        _env_file=None, database_path=str(db_path), data_dir=str(tmp_path / "files"),
        trace_dir=str(tmp_path / "traces"),
    )
    return Env(conn, clock, settings, load_app_config(ROOT / "config.yaml"))
