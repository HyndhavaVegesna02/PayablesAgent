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


def make_mail_env(tmp_path: Path) -> Env:
    """A seeded env whose worker reads its own empty test inbox, with a fresh
    Fernet key for the document store."""
    from cryptography.fernet import Fernet

    env = make_env(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    env.settings = env.settings.model_copy(update={
        "fernet_key": Fernet.generate_key().decode(), "test_inbox_path": str(inbox), "mail_source": "eml_folder",
    })
    return env


def deliver(env: Env, *names: str) -> None:
    import shutil

    for name in names:
        shutil.copy(ROOT / "fixtures" / "test_inbox" / name, env.settings.test_inbox_path)


def run_all(env: Env, handlers, limit: int = 100) -> None:
    """Runs due jobs until none is left (jobs with no handler stay queued)."""
    from app.worker import process_one

    for _ in range(limit):
        if not process_one(env.conn, handlers, clock=env.clock, settings=env.settings,
                           app_config=env.app_config):
            return
    raise AssertionError("the queue did not drain")
