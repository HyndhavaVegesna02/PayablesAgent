"""The job runner (batch 2 plan, CHG-013 AC1 and AC7): dispatch by kind,
retry with backoff, dead-letter, permanent errors, unregistered kinds, the
heartbeat, and recovery of a job a stopped worker left running."""

import threading
from datetime import timedelta

import pytest

from app import worker
from app.jobs import queue
from app.worker import PermanentJobError, backoff, process_one
from tests.worker_helpers import make_env


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path, seeded=False)
    yield e
    e.conn.close()


def _run(env, handlers):
    return process_one(env.conn, handlers, clock=env.clock, settings=env.settings,
                       app_config=env.app_config)


def _job(env, job_id):
    return env.conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()


def _enqueue(env, kind="replan", payload=None, **kw):
    job_id = queue.enqueue(env.conn, kind=kind, payload=payload or {}, clock=env.clock, **kw)
    env.conn.commit()
    return job_id


def test_a_job_is_dispatched_by_kind_and_marked_done(env):
    seen = []
    job_id = _enqueue(env, "replan", {"business_id": 7})
    other = _enqueue(env, "monday_plan")

    assert _run(env, {"replan": lambda ctx: seen.append(("replan", ctx.payload))}) is True

    assert seen == [("replan", {"business_id": 7})]
    assert _job(env, job_id)["status"] == "done"
    assert _job(env, other)["status"] == "queued"  # no handler given for it


def test_no_due_job_returns_false(env):
    _enqueue(env, run_after=(env.clock.now() + timedelta(minutes=1)).isoformat())
    assert _run(env, {"replan": lambda ctx: None}) is False


def test_a_kind_with_no_handler_is_never_claimed_or_dead_lettered(env):
    job_id = _enqueue(env, "run_case")
    for _ in range(10):
        assert _run(env, {"replan": lambda ctx: None}) is False
    row = _job(env, job_id)
    assert (row["status"], row["attempts"]) == ("queued", 0)


def test_backoff_doubles_from_thirty_seconds_and_caps_at_an_hour():
    assert [backoff(n) for n in (1, 2, 3, 4)] == [
        timedelta(seconds=30), timedelta(seconds=60), timedelta(seconds=120), timedelta(seconds=240),
    ]
    assert backoff(8) == timedelta(hours=1)
    assert backoff(30) == timedelta(hours=1)


def test_a_failing_job_is_retried_with_backoff_then_dead_lettered(env):
    def boom(ctx):
        raise RuntimeError("database is locked")

    job_id = _enqueue(env)
    start = env.clock.now()
    delays = []
    for attempt in range(1, 6):
        assert _run(env, {"replan": boom}) is True
        row = _job(env, job_id)
        assert row["attempts"] == attempt
        assert "database is locked" in row["last_error"]
        if attempt < 5:
            assert row["status"] == "queued"
            delays.append(row["run_after"])
            # not due again until its backoff has passed
            assert _run(env, {"replan": boom}) is False
            env.clock.advance(backoff(attempt))
    assert _job(env, job_id)["status"] == "dead"
    assert delays[0] == (start + timedelta(seconds=30)).isoformat()


def test_a_permanent_error_dead_letters_at_once(env):
    def refuse(ctx):
        raise PermanentJobError("400 INVALID_ARGUMENT")

    job_id = _enqueue(env)
    _run(env, {"replan": refuse})
    row = _job(env, job_id)
    assert (row["status"], row["attempts"]) == ("dead", 1)
    assert row["last_error"] == "permanent: 400 INVALID_ARGUMENT"


@pytest.mark.parametrize("payload", ["not json", "[1, 2]"])
def test_a_malformed_payload_dead_letters_without_calling_the_handler(env, payload):
    job_id = _enqueue(env)
    env.conn.execute("UPDATE job SET payload_json = ? WHERE id = ?", (payload, job_id))
    env.conn.commit()
    called = []
    _run(env, {"replan": lambda ctx: called.append(1)})
    assert called == []
    assert _job(env, job_id)["status"] == "dead"


def test_a_failed_handler_leaves_none_of_its_writes(env):
    def half_done(ctx):
        ctx.conn.execute("INSERT INTO sync_state (source, last_synced_at) VALUES ('eml_folder', 'x')")
        raise RuntimeError("crashed part-way")

    _enqueue(env)
    _run(env, {"replan": half_done})
    assert env.conn.execute("SELECT COUNT(*) FROM sync_state").fetchone()[0] == 0


def test_the_handler_gets_a_tracer_named_for_the_job_and_attempt(env):
    names = []
    job_id = _enqueue(env)

    def fail_once(ctx):
        names.append(ctx.tracer.run_id)
        if len(names) == 1:
            raise RuntimeError("first try fails")

    _run(env, {"replan": fail_once})
    env.clock.advance(backoff(1))
    _run(env, {"replan": fail_once})
    assert names == [f"job-{job_id}-attempt-1", f"job-{job_id}-attempt-2"]


def test_mark_failed_permanent_is_dead_even_with_attempts_left(env):
    job_id = _enqueue(env, max_attempts=5)
    queue.mark_failed(env.conn, job_id, "nope", permanent=True)
    assert (_job(env, job_id)["status"], _job(env, job_id)["attempts"]) == ("dead", 1)


def test_run_requeues_a_job_left_running_writes_a_heartbeat_and_stops(env):
    stuck = _enqueue(env)
    env.conn.execute("UPDATE job SET status = 'running', locked_at = 'x' WHERE id = ?", (stuck,))
    env.conn.commit()
    stop = threading.Event()
    ran = []

    def handler(ctx):
        ran.append(ctx.job["id"])
        stop.set()

    t = threading.Thread(
        target=worker.run,
        args=(env.settings, env.app_config, {"replan": handler}),
        kwargs={"clock": env.clock, "stop": stop, "idle_seconds": 0.01},
    )
    t.start()
    t.join(timeout=10)
    assert not t.is_alive()
    assert ran == [stuck]
    assert _job(env, stuck)["status"] == "done"
    assert worker.read_heartbeat(env.settings) == env.clock.now().isoformat()


def test_read_heartbeat_is_none_before_the_worker_has_run(env):
    assert worker.read_heartbeat(env.settings) is None


def test_default_handlers_cover_the_jobs_this_change_owns():
    assert set(worker.default_handlers()) == {
        "replan", "monday_plan", "reconcile_txn", "reconcile_failure", "drift_check",
    }

