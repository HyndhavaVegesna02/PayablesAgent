"""The worker process (TDD Part 2, "Jobs and the document pipeline"): claims
one job at a time, runs its handler, retries failures with backoff and marks
a job dead after max_attempts. APScheduler only enqueues jobs; the work itself
always runs here, from the job table, so nothing is lost if the worker stops.

Only kinds that have a handler are claimed. A job whose handler lands in a
later change (run_case before CHG-008) waits in the queue instead of being
dead-lettered (batch 2 plan, Q10).

`python -m app.worker` (or `make worker`) runs it."""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.clock import TIMEZONE, Clock, clock_for
from app.config import AppConfig, Settings, load_app_config
from app.db.connection import write_connection
from app.jobs import queue
from app.jobs.queue import PermanentJobError
from app.trace.tracer import Tracer

BACKOFF_FIRST = timedelta(seconds=30)
BACKOFF_CAP = timedelta(hours=1)
HEARTBEAT_FILE = "worker.heartbeat"


@dataclass
class JobContext:
    conn: sqlite3.Connection
    job: sqlite3.Row
    payload: dict[str, Any]
    clock: Clock
    tracer: Tracer
    settings: Settings
    app_config: AppConfig


Handler = Callable[[JobContext], None]


def backoff(failed_attempts: int) -> timedelta:
    """Delay before retry number `failed_attempts`: 30s, 1m, 2m, ... capped at 1h."""
    return min(BACKOFF_FIRST * 2 ** (failed_attempts - 1), BACKOFF_CAP)


def run_id_for(job: sqlite3.Row) -> str:
    return f"job-{job['id']}-attempt-{job['attempts'] + 1}"


def process_one(
    conn: sqlite3.Connection,
    handlers: Mapping[str, Handler],
    *,
    clock: Clock,
    settings: Settings,
    app_config: AppConfig,
) -> bool:
    """Claims and runs one due job. Returns False when there was none."""
    if not handlers:
        return False  # claim_one with no kinds would claim every kind
    job = queue.claim_one(conn, kinds=sorted(handlers), clock=clock)
    conn.commit()
    if job is None:
        return False
    tracer = Tracer(run_id_for(job), settings.trace_dir, clock)
    tracer.attempt = job["attempts"] + 1
    try:
        try:
            payload = json.loads(job["payload_json"])
        except json.JSONDecodeError as e:
            raise PermanentJobError(f"payload is not JSON: {e}") from e
        if not isinstance(payload, dict):
            raise PermanentJobError("payload is not a JSON object")
        handlers[job["kind"]](
            JobContext(conn, job, payload, clock, tracer, settings, app_config)
        )
    except PermanentJobError as e:
        conn.rollback()
        queue.mark_failed(conn, job["id"], f"permanent: {e}", permanent=True)
    except Exception as e:  # noqa: BLE001 - every other failure is retried, then dead-lettered
        conn.rollback()
        retry_at = (clock.now() + backoff(job["attempts"] + 1)).isoformat()
        queue.mark_failed(conn, job["id"], repr(e), retry_at=retry_at)
    else:
        queue.mark_done(conn, job["id"])
    conn.commit()
    return True


# --- heartbeat --------------------------------------------------------------------


def heartbeat_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / HEARTBEAT_FILE


def write_heartbeat(settings: Settings, clock: Clock) -> None:
    path = heartbeat_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(clock.now().isoformat(), encoding="utf-8")
    tmp.replace(path)  # the web process never reads a half-written file


def read_heartbeat(settings: Settings) -> str | None:
    try:
        return heartbeat_path(settings).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# --- scheduler --------------------------------------------------------------------


def schedule_jobs(
    scheduler: BaseScheduler,
    *,
    db_path: str | Path,
    app_config: AppConfig,
    clock: Clock,
    kinds: Iterable[str],
    demo: bool = False,
) -> None:
    """Registers the timed jobs. A trigger only enqueues a row; it never runs
    work itself. Kinds with no handler yet are not scheduled at all, so they
    cannot pile up in the queue. In demo mode the Monday plan is not on a
    real-time cron: moving the demo clock past Monday 07:00 enqueues it (D14)."""
    kinds = set(kinds)
    if "monday_plan" in kinds and not demo:
        scheduler.add_job(
            enqueue_monday_plan, CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=TIMEZONE),
            kwargs={"db_path": db_path, "clock": clock}, id="monday_plan", replace_existing=True,
            misfire_grace_time=6 * 3600, coalesce=True,  # a worker started late on Monday still plans
        )
    if "poll_mail" in kinds:
        scheduler.add_job(
            enqueue_poll_mail, IntervalTrigger(minutes=app_config.mail.poll_minutes, timezone=TIMEZONE),
            kwargs={"db_path": db_path, "clock": clock}, id="poll_mail", replace_existing=True,
        )


def enqueue_monday_plan(*, db_path: str | Path, clock: Clock) -> None:
    conn = write_connection(db_path)
    try:
        queue.enqueue_monday_plans(conn, clock=clock)
        conn.commit()
    finally:
        conn.close()


def enqueue_poll_mail(*, db_path: str | Path, clock: Clock) -> None:
    conn = write_connection(db_path)
    try:
        queue.enqueue_poll_mail(conn, clock=clock)
        conn.commit()
    finally:
        conn.close()


# --- the loop ---------------------------------------------------------------------


def default_handlers(backend=None) -> dict[str, Handler]:
    """Every job this build can run. Mail jobs and the exception agent need an
    AI backend; without one they are not registered, so their jobs wait in the
    queue (Q10). explain_plan runs either way: without AI its note is the template."""
    from app.jobs import alerts, explain, reconcile, replan

    out: dict[str, Handler] = {"replan": replan.handle_replan, "monday_plan": replan.handle_monday_plan}
    out.update(reconcile.handlers())
    out.update(explain.handlers(backend))  # without AI, its notes are the template
    out.update(alerts.handlers())  # without an SMTP host, alerts wait unsent
    if backend is not None:
        from app.ingest import pipeline
        from app.jobs import run_case

        out.update(pipeline.handlers(backend))
        out.update(run_case.handlers(backend))
    return out


def run(
    settings: Settings,
    app_config: AppConfig,
    handlers: Mapping[str, Handler],
    *,
    clock: Clock,
    stop: threading.Event,
    idle_seconds: float = 1.0,
) -> None:
    """Runs jobs until `stop` is set. A heartbeat the OS will not let us write
    (Windows refuses to replace a file another process has open) or a busy
    database is logged and retried on the next loop; it never stops the worker."""
    conn = write_connection(settings.database_path)
    try:
        queue.requeue_running(conn)
        conn.commit()
        while not stop.is_set():
            try:
                write_heartbeat(settings, clock)
            except OSError as e:
                print(f"worker: heartbeat not written ({e}); will retry", file=sys.stderr)
            try:
                worked = process_one(conn, handlers, clock=clock, settings=settings, app_config=app_config)
            except sqlite3.OperationalError as e:
                conn.rollback()
                print(f"worker: database busy ({e}); will retry", file=sys.stderr)
                worked = False
                try:  # a job claimed before the error must not stay `running` until a restart
                    queue.requeue_running(conn)
                    conn.commit()
                except sqlite3.OperationalError:
                    conn.rollback()
            if not worked:
                stop.wait(idle_seconds)
    finally:
        conn.close()


def build_backend(settings: Settings, app_config: AppConfig):
    """The worker's AI: the demo's canned fixture replies (DEMO_AI=fixtures,
    D15: never Gemini, recorded as model fixture-ai with no tokens or cost),
    Gemini when a key is set, or none."""
    if settings.demo_ai == "fixtures":
        from app.ai.fixture_backend import FIXTURE_MODEL, FixtureBackend

        free = app_config.model.pricing.model_copy(update={"input_micro_usd_per_mtok": 0,
                                                            "output_micro_usd_per_mtok": 0})
        model = app_config.model.model_copy(update={"id": FIXTURE_MODEL, "pricing": free})
        store = Path(settings.fixture_replies_path) if settings.fixture_replies_path.strip() else None
        return FixtureBackend(store), app_config.model_copy(update={"model": model})
    if settings.gemini_api_key.strip():
        from app.ai.client import GeminiBackend

        return GeminiBackend(settings.gemini_api_key, timeout_ms=app_config.ai.timeout_ms), app_config
    return None, app_config


def main() -> int:
    from apscheduler.schedulers.background import BackgroundScheduler

    settings = Settings()
    clock = clock_for(settings.demo_now, settings.data_dir)
    backend, app_config = build_backend(settings, load_app_config(settings.app_config_path))
    if backend is None:
        print("worker: GEMINI_API_KEY is not set, so mail is not polled or processed", file=sys.stderr)
    handlers = default_handlers(backend)
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    schedule_jobs(scheduler, db_path=settings.database_path, app_config=app_config, clock=clock,
                  kinds=handlers, demo=bool(settings.demo_now))
    scheduler.start()
    stop = threading.Event()
    print(f"worker: running {sorted(handlers)} against {settings.database_path}")
    try:
        run(settings, app_config, handlers, clock=clock, stop=stop)
    except KeyboardInterrupt:
        stop.set()
    finally:
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
