"""Timed jobs (batch 2 plan, CHG-013 AC6): monday_plan at Mon 07:00
Asia/Kolkata, poll_mail every mail.poll_minutes. Triggers only enqueue rows;
next fire times are computed from the injected Clock."""

from datetime import datetime, timedelta

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.clock import TIMEZONE, FakeClock
from app.jobs.replan import handle_monday_plan
from app.worker import enqueue_monday_plan, enqueue_poll_mail, process_one, schedule_jobs
from tests.worker_helpers import make_env


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


def _scheduled(env, kinds):
    scheduler = BackgroundScheduler(timezone=TIMEZONE)  # never started: nothing fires
    schedule_jobs(scheduler, db_path=env.settings.database_path, app_config=env.app_config,
                  clock=env.clock, kinds=kinds)
    return {j.id: j for j in scheduler.get_jobs()}


def _next_fire(job, at: datetime):
    return job.trigger.get_next_fire_time(None, at)


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 10, 9, 18, 0), datetime(2026, 10, 12, 7, 0)),    # Fri evening -> Mon 07:00
    (datetime(2026, 10, 12, 6, 59), datetime(2026, 10, 12, 7, 0)),   # Mon just before
    (datetime(2026, 10, 12, 7, 0, 1), datetime(2026, 10, 19, 7, 0)), # Mon just after -> next week
])
def test_monday_plan_fires_at_monday_seven_in_kolkata(env, now, expected):
    job = _scheduled(env, ["monday_plan"])["monday_plan"]
    clock = FakeClock(now.replace(tzinfo=TIMEZONE))
    fire = _next_fire(job, clock.now())
    assert fire == expected.replace(tzinfo=TIMEZONE)
    assert fire.utcoffset() == timedelta(hours=5, minutes=30)  # wall-clock IST, not UTC


def test_poll_mail_runs_every_configured_interval(env):
    job = _scheduled(env, ["poll_mail"])["poll_mail"]
    assert job.trigger.interval == timedelta(minutes=env.app_config.mail.poll_minutes)


def test_a_kind_without_a_handler_is_not_scheduled(env):
    assert set(_scheduled(env, ["replan", "monday_plan"])) == {"monday_plan"}


def test_monday_enqueue_is_once_per_business_per_day(env):
    for _ in range(3):
        enqueue_monday_plan(db_path=env.settings.database_path, clock=env.clock)
    rows = env.conn.execute("SELECT kind, payload_json, idempotency_key FROM job").fetchall()
    assert [tuple(r) for r in rows] == [("monday_plan", '{"business_id": 1}', "monday_plan:1:2026-10-12")]
    env.clock.advance(timedelta(days=7))
    enqueue_monday_plan(db_path=env.settings.database_path, clock=env.clock)
    assert env.conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 2


def test_a_queued_poll_absorbs_the_next_tick(env):
    for _ in range(3):
        enqueue_poll_mail(db_path=env.settings.database_path, clock=env.clock)
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'poll_mail'").fetchone()[0] == 1


def test_the_monday_job_runs_a_replan_triggered_by_monday(env):
    enqueue_monday_plan(db_path=env.settings.database_path, clock=env.clock)
    assert process_one(env.conn, {"monday_plan": handle_monday_plan}, clock=env.clock,
                       settings=env.settings, app_config=env.app_config)
    run = env.conn.execute("SELECT triggered_by, is_current FROM plan_run").fetchall()
    assert [tuple(r) for r in run] == [("monday", 1)]
    assert env.conn.execute("SELECT status FROM job").fetchone()[0] == "done"


def test_a_monday_plan_missed_while_the_worker_was_down_still_runs_once(env):
    job = _scheduled(env, ["monday_plan"])["monday_plan"]
    assert job.misfire_grace_time == 6 * 3600 and job.coalesce is True
