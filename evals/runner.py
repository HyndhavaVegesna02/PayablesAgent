"""The eval runner (TDD Part 1, "Evaluation"; batch 7, CHG-010a).

Each run plays one scenario on a fresh copy of the seeded worked example: its
own database, document store, clock, inbox and trace directory. Mail arrives
by the test inbox and the real poll; uploads and the owner's answers go
through the same functions the web app calls; the real worker runs every job.
Nothing in a run is shared with another, so N runs are N independent results.

    python -m evals.runner --ai fixtures --runs 1 [--scenario NAME] [--config VARIANT.yaml] [--label X]

The model is the only thing that differs between `--ai fixtures` (canned
replies, offline, deterministic) and `--ai live` (Gemini, behind the budget
guard of evals/budget.py)."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from app.ai.client import Backend
from app.ai.fixture_backend import FIXTURE_UPLOADS
from app.clock import TIMEZONE, FakeClock
from app.config import AppConfig, Settings
from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from app.ingest.store import DocumentStore
from app.jobs import queue
from app.web import actions, repo
from app.web.auth import User
from app.web.routes.attention import prefill
from app.worker import default_handlers, process_one
from evals.scenario import COMPONENTS, Expectation, Scenario
from fixtures.seed import seed

ROOT = Path(__file__).resolve().parent.parent
INBOXES = (ROOT / "fixtures" / "agent_inbox", ROOT / "fixtures" / "test_inbox")
START = datetime(2026, 10, 12, 9, 0, tzinfo=TIMEZONE)  # Mon 12 Oct 2026, the worked example's Monday
OWNER = User(1, 1, "owner@example.test", "owner")
HELPER = User(2, 1, "helper@example.test", "helper")
MAX_JOBS = 500  # per drain: a scenario that queues more is looping
MAX_RETRY_WAIT_S = 3600  # a retry due within an hour of fake time is waited for


def never() -> str | None:
    """A stop hook that never stops (fixture mode)."""
    return None


class StopRun(Exception):
    """Raised by a should_stop hook (the budget guard): the run stops, ERRORED."""


@dataclass
class RunEnv:
    conn: Any
    clock: FakeClock
    settings: Settings
    app_config: AppConfig
    handlers: dict
    store: DocumentStore
    scenario: Scenario
    should_stop: Callable[[], str | None] = never


@dataclass
class Check:
    id: str
    component: str
    ok: bool
    got: Any
    want: Any


@dataclass
class RunResult:
    scenario: str
    run: int
    status: str  # PASSED, FAILED or ERRORED
    checks: list[Check] = field(default_factory=list)
    component: str | None = None  # the first failed check's, in pipeline order
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def met(self) -> float:
        return sum(c.ok for c in self.checks) / len(self.checks) if self.checks else 0.0


# --- the worker -------------------------------------------------------------------------


def drain(env: RunEnv) -> None:
    """Runs due jobs until none is due. A job waiting to retry (it failed, and
    its retry is due within the hour) is waited for by moving the clock: the
    run's fake time, never real time."""
    for _ in range(MAX_JOBS):
        reason = env.should_stop()
        if reason:
            raise StopRun(reason)
        if process_one(env.conn, env.handlers, clock=env.clock, settings=env.settings, app_config=env.app_config):
            continue
        row = env.conn.execute(
            "SELECT MIN(run_after) FROM job WHERE status = 'queued' AND attempts > 0 AND kind IN (%s)"
            % ",".join("?" * len(env.handlers)), sorted(env.handlers)).fetchone()
        retry = datetime.fromisoformat(row[0]) if row[0] else None
        if retry is None or (retry - env.clock.now()).total_seconds() > MAX_RETRY_WAIT_S:
            return
        if retry > env.clock.now():
            env.clock.advance(retry - env.clock.now())
    raise RuntimeError(f"more than {MAX_JOBS} jobs in one drain: the scenario is looping")


def _enqueue(env: RunEnv, kind: str, payload: dict | None = None) -> None:
    queue.enqueue(env.conn, kind=kind, payload=payload or {}, clock=env.clock)
    env.conn.commit()
    drain(env)


# --- steps ---------------------------------------------------------------------------------


def _find(env: RunEnv, name: str, folders: tuple[Path, ...]) -> Path:
    for folder in (env.scenario.folder, *folders):
        if folder is not None and (folder / name).is_file():
            return folder / name
    raise FileNotFoundError(f"{env.scenario.name}: no fixture named {name}")


def _at(env: RunEnv, when: str) -> None:
    target = datetime.fromisoformat(when).replace(tzinfo=TIMEZONE)
    if target < env.clock.now():
        raise ValueError(f"{env.scenario.name}: 'at {when}' is before the run's clock ({env.clock.now()})")
    env.clock.advance(target - env.clock.now())


def _deliver(env: RunEnv, names: list[str]) -> None:
    for name in names:
        shutil.copy(_find(env, name, INBOXES), env.settings.test_inbox_path)


def _upload(env: RunEnv, spec: dict) -> None:
    content = _find(env, spec["file"], (FIXTURE_UPLOADS,)).read_bytes()
    actions.upload(env.conn, HELPER, content, spec["kind"], env.store, clock=env.clock)
    env.conn.commit()
    drain(env)


def _approve(env: RunEnv, _: Any) -> None:
    view = repo.plan_view(env.conn, OWNER.business_id)
    actions.approve(env.conn, OWNER, view.run["id"], {ln.payable_id: ln.version for ln in view.to_approve},
                    clock=env.clock)
    env.conn.commit()
    drain(env)


def _confirm_waiting(env: RunEnv, _: Any) -> None:
    for cand in repo.waiting_candidates(env.conn, OWNER.business_id):
        actions.confirm_candidate(env.conn, OWNER, cand["id"], prefill(cand, repo.accounts(env.conn, 1)),
                                  clock=env.clock)
        env.conn.commit()
    drain(env)


def _unlock(env: RunEnv, spec: dict) -> None:
    (doc_id,) = env.conn.execute("SELECT id FROM source_document WHERE status = 'LOCKED' ORDER BY id").fetchone()
    actions.unlock_document(env.conn, OWNER, doc_id, spec["password"], env.store, clock=env.clock)
    env.conn.commit()
    drain(env)


def _confirm_balance(env: RunEnv, spec: dict) -> None:
    actions.confirm_balance(env.conn, OWNER, spec.get("account_id", 1), spec["amount"], clock=env.clock)
    env.conn.commit()
    drain(env)


def _choose_option(env: RunEnv, kind: str) -> None:
    (option_id,) = env.conn.execute(
        "SELECT o.id FROM shortfall_option o JOIN plan_run r ON r.id = o.plan_run_id WHERE r.is_current = 1 "
        "AND o.kind = ? ORDER BY o.id", (kind,)).fetchone()
    actions.choose_option(env.conn, OWNER, option_id, clock=env.clock)
    env.conn.commit()
    drain(env)


STEPS: dict[str, Callable[[RunEnv, Any], None]] = {
    "at": _at,
    "deliver": _deliver,
    "poll": lambda env, _: _enqueue(env, "poll_mail"),
    "drain": lambda env, _: drain(env),
    "monday_plan": lambda env, _: _enqueue(env, "monday_plan", {"business_id": 1}),
    "approve": _approve,
    "upload": _upload,
    "confirm_waiting": _confirm_waiting,
    "unlock": _unlock,
    "confirm_balance": _confirm_balance,
    "choose_option": _choose_option,
}


# --- checks ------------------------------------------------------------------------------------


def check(conn, e: Expectation) -> Check:
    rows = [list(r) for r in conn.execute(e.sql).fetchall()]
    if e.rows is not None:
        return Check(e.id, e.component, rows == e.rows, rows, e.rows)
    got = rows[0][0] if rows else None
    return Check(e.id, e.component, got == e.equals, got, e.equals)


def first_failed_component(checks: list[Check]) -> str | None:
    failed = {c.component for c in checks if not c.ok}
    return next((c for c in COMPONENTS if c in failed), None)


# --- one run -----------------------------------------------------------------------------------


def make_env(tmp: Path, scenario: Scenario, backend: Backend, app_config: AppConfig) -> RunEnv:
    db = tmp / "eval.db"
    apply_migrations(db)
    conn = write_connection(db)
    clock = FakeClock(START)
    seed(conn, clock)
    conn.commit()
    (tmp / "inbox").mkdir()
    settings = Settings(_env_file=None, database_path=str(db), data_dir=str(tmp / "files"),
                        trace_dir=str(tmp / "traces"), fernet_key=Fernet.generate_key().decode(),
                        test_inbox_path=str(tmp / "inbox"), mail_source="eml_folder")
    return RunEnv(conn, clock, settings, app_config, default_handlers(backend),
                  DocumentStore(settings.data_dir, settings.fernet_key), scenario)


def run_once(scenario: Scenario, backend: Backend, app_config: AppConfig, run: int = 1, *,
             should_stop: Callable[[], str | None] = never,
             inspect: Callable[[RunEnv], dict[str, Any]] | None = None, keep: Path | None = None) -> RunResult:
    """Plays the scenario once and checks it. `inspect` reads the finished run
    (its traces and jobs) before the run's files are removed; `keep` copies
    the run's traces there."""
    with tempfile.TemporaryDirectory(prefix=f"eval-{scenario.name}-") as tmp_name:
        tmp = Path(tmp_name)
        env = make_env(tmp, scenario, backend, app_config)
        env.should_stop = should_stop
        result = RunResult(scenario.name, run, "PASSED")
        try:
            for step in scenario.steps:
                ((kind, arg),) = step.items()
                STEPS[kind](env, arg)
            result.checks = [check(env.conn, e) for e in scenario.expect]
            if not all(c.ok for c in result.checks):
                result.status, result.component = "FAILED", first_failed_component(result.checks)
        except StopRun as e:
            result.status, result.error = "ERRORED", str(e)
        except Exception as e:  # noqa: BLE001 - a crash is the system failing the scenario
            result.status, result.error, result.component = "FAILED", f"{type(e).__name__}: {e}", "crash"
            result.checks = [check(env.conn, e2) for e2 in scenario.expect]
        if inspect is not None:
            result.metrics = inspect(env)
        if keep is not None and (tmp / "traces").is_dir():
            shutil.copytree(tmp / "traces", keep / f"{scenario.name}-run{run}", dirs_exist_ok=True)
        env.conn.close()
    return result


# --- a suite: scenarios x runs, under one config -------------------------------------------


def load_config(variant: Path | None = None) -> tuple[AppConfig, str]:
    """config.yaml, with a variant's keys merged over it (TDD change control:
    the model and prompt settings live in config), and the merged result's hash."""
    import hashlib
    import json

    import yaml

    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    def merge(base: dict, over: dict) -> dict:
        return {**base, **{k: merge(base.get(k, {}), v) if isinstance(v, dict) and isinstance(base.get(k), dict)
                           else v for k, v in over.items()}}

    if variant is not None:
        raw = merge(raw, yaml.safe_load(Path(variant).read_text(encoding="utf-8")) or {})
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
    return AppConfig.model_validate(raw), digest


def run_suite(scenarios: list[Scenario], backend_factory: Callable[[], Backend], config: AppConfig, runs: int, *,
              should_stop: Callable[[], str | None] = never, keep: Path | None = None,
              progress: Callable[[RunResult], None] = lambda r: None) -> tuple[list[RunResult], str | None]:
    """Every scenario, `runs` times, one after another. Returns the results and,
    if the stop hook ended the suite early, why."""
    from evals import metrics

    results: list[RunResult] = []
    for s in scenarios:
        for i in range(1, runs + 1):
            reason = should_stop()
            if reason:
                return results, reason
            r = run_once(s, backend_factory(), config, i, should_stop=should_stop, inspect=metrics.inspect, keep=keep)
            results.append(r)
            progress(r)
    return results, None


# --- command line ---------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    from app.ai.fixture_backend import FixtureBackend
    from app.clock import SystemClock
    from evals import report
    from evals import scenario as scenarios

    p = argparse.ArgumentParser(prog="python -m evals.runner", description="Run the eval scenarios and write a report.")
    p.add_argument("--ai", choices=["fixtures", "live"], required=True,
                   help="fixtures: canned replies, offline; live: Gemini, behind the budget guard")
    p.add_argument("--runs", type=int, default=5, help="runs per scenario (default 5)")
    p.add_argument("--scenario", action="append", help="only this scenario (repeatable)")
    p.add_argument("--config", type=Path, help="a variant merged over config.yaml (evals/variants/)")
    p.add_argument("--label", default="baseline")
    p.add_argument("--out", type=Path, default=ROOT / "docs" / "evals")
    p.add_argument("--keep-traces", action="store_true", help="copy each run's traces next to the report")
    p.add_argument("--yes-spend", action="store_true", help="required with --ai live")
    args = p.parse_args(argv)

    config, config_hash = load_config(args.config)
    chosen = [scenarios.load(n) for n in (args.scenario or scenarios.names())]
    today = SystemClock().now()
    out_dir = args.out / f"{today.date().isoformat()}-{args.ai}-{args.label}"
    should_stop: Callable[[], str | None] = never
    if args.ai == "fixtures":
        backend_factory: Callable[[], Backend] = FixtureBackend
    else:
        from evals.budget import live_backend

        backend_factory, should_stop = live_backend(config, confirmed=args.yes_spend)
    results, stopped = run_suite(
        chosen, backend_factory, config, args.runs, should_stop=should_stop,
        keep=out_dir / "traces" if args.keep_traces else None,
        progress=lambda r: print(f"{r.status:8} {r.scenario} run {r.run}"
                                 + (f"  [{r.component}] {r.error or ''}" if r.component or r.error else ""), flush=True))
    meta = {"label": args.label, "mode": args.ai, "model": config.model.id, "prompt_version": config.prompts.version,
            "config_sha256": config_hash, "variant": args.config.as_posix() if args.config else None,
            "commit": report.git_commit(), "date": today.isoformat(timespec="seconds"),
            "runs_per_scenario": args.runs, "status": "COMPLETE" if stopped is None else "ABORTED",
            "stopped_because": stopped}
    built = report.build(meta, chosen, results)
    report.write(built, out_dir)
    t = built["totals"]
    print(f"{t['passed']}/{t['runs']} runs passed; report: {out_dir}")
    return 0 if t["passed"] == t["runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
