"""Demo mode (batch 3 plan, PO decisions D14 and D15): one demo clock that the
web app and the worker both read, moved forward by hand; and the fixture AI,
which answers from the test inbox's canned replies and never calls Gemini."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import demo
from app.ai.client import AIUnavailable
from app.ai.fixture_backend import FIXTURE_MODEL, FixtureBackend
from app.clock import DEMO_CLOCK_FILE, TIMEZONE, DemoClock, SystemClock, clock_for
from app.config import Settings
from app.ingest.eml_folder import EmlFolderSource
from app.jobs import queue
from app.main import create_app
from app.worker import build_backend, default_handlers, schedule_jobs
from tests.web_helpers import HELPER, login, post
from tests.worker_helpers import ROOT, deliver, make_mail_env, run_all

INBOX = ROOT / "fixtures" / "test_inbox"
START = "2026-10-12T09:00:00+05:30"


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TIMEZONE)


@pytest.fixture
def demo_env(tmp_path):
    env = make_mail_env(tmp_path)
    env.settings = env.settings.model_copy(update={"session_secret": "test-session-secret", "demo_now": START})
    env.clock = clock_for(env.settings.demo_now, env.settings.data_dir)
    yield env
    env.conn.close()


def _client(env):
    return TestClient(create_app(env.settings, app_config=env.app_config))  # the app picks its own clock


# --- D14: one clock ---------------------------------------------------------------------


def test_outside_a_demo_the_clock_is_real_time(tmp_path):
    assert isinstance(clock_for("", tmp_path), SystemClock)


def test_the_web_app_and_the_worker_read_the_same_demo_instant(tmp_path):
    web_clock, worker_clock = clock_for(START, tmp_path), clock_for(START, tmp_path)
    assert web_clock.now() == worker_clock.now() == at(12, 9)
    web_clock.set(at(15, 9))
    assert worker_clock.now() == at(15, 9) and worker_clock.today().isoformat() == "2026-10-15"
    assert (tmp_path / DEMO_CLOCK_FILE).read_text(encoding="utf-8") == "2026-10-15T09:00:00+05:30"


def test_time_stands_still_and_never_moves_backwards(tmp_path):
    clock = DemoClock(tmp_path / DEMO_CLOCK_FILE, at(12, 9))
    assert clock.now() == clock.now() == at(12, 9)
    clock.set(at(15, 9))
    with pytest.raises(ValueError, match="only moves forward"):
        clock.set(at(14, 9))
    with pytest.raises(ValueError, match="UTC offset"):
        clock.set(datetime(2026, 10, 16, 9))
    assert clock.now() == at(15, 9)


def test_advancing_the_clock_releases_the_next_fixture_email(tmp_path):
    clock = DemoClock(tmp_path / DEMO_CLOCK_FILE, at(12, 9))
    source = EmlFolderSource(INBOX, clock)
    names = lambda: [r.id for r in source.list_new(at(1, 0).date(), ["alerts@hdfcbank.example"])]  # noqa: E731
    assert "07-credit-nandi-foods.eml" not in names() and "01-debit-ashirwad-paper.eml" not in names()
    clock.set(at(16, 11))
    assert "07-credit-nandi-foods.eml" in names()


def test_moving_past_monday_seven_enqueues_that_mondays_plan(demo_env):
    env = demo_env
    demo.advance(env.conn, env.clock, at(18, 20))  # Sun: no Monday crossed since Mon 12 09:00
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'monday_plan'").fetchone()[0] == 0
    demo.advance(env.conn, env.clock, at(19, 9))
    job = env.conn.execute("SELECT * FROM job WHERE kind = 'monday_plan'").fetchone()
    assert job["idempotency_key"] == "monday_plan:1:2026-10-19"
    demo.advance(env.conn, env.clock, at(19, 10))  # no second plan for the same Monday
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'monday_plan'").fetchone()[0] == 1


def test_each_move_queues_one_mail_poll(demo_env):
    env = demo_env
    demo.advance(env.conn, env.clock, at(15, 9))
    demo.advance(env.conn, env.clock, at(16, 11))
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'poll_mail' AND status = 'queued'").fetchone()[0] == 1


def test_advance_refuses_outside_a_demo(tmp_path, demo_env):
    with pytest.raises(demo.NotADemo):
        demo.advance(demo_env.conn, SystemClock(), at(15, 9))


def test_the_demo_worker_has_no_real_time_monday_cron(demo_env):
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    schedule_jobs(scheduler, db_path=demo_env.settings.database_path, app_config=demo_env.app_config,
                  clock=demo_env.clock, kinds=["monday_plan", "poll_mail"], demo=True)
    assert {j.id for j in scheduler.get_jobs()} == {"poll_mail"}


def test_the_demo_time_command(demo_env, monkeypatch, capsys):
    for key, value in (("DATABASE_PATH", demo_env.settings.database_path), ("DATA_DIR", demo_env.settings.data_dir),
                       ("DEMO_NOW", START)):
        monkeypatch.setenv(key, value)
    assert demo.main(["2026-10-15T09:00"]) == 0  # no offset: India time
    assert "it is now 2026-10-15T09:00:00+05:30" in capsys.readouterr().out
    assert demo.main(["2026-10-14T09:00+05:30"]) == 1
    assert "only moves forward" in capsys.readouterr().err
    monkeypatch.setenv("DEMO_NOW", "")
    assert demo.main(["2026-10-16T09:00+05:30"]) == 1


def test_reseeding_a_demo_starts_the_clock_again(demo_env, monkeypatch, capsys):
    from fixtures import seed as seed_module

    clock_file = Path(demo_env.settings.data_dir) / DEMO_CLOCK_FILE
    demo_env.clock.set(at(16, 11))
    db_path = Path(demo_env.settings.data_dir).parent / "reseed.db"
    for key, value in (("DATABASE_PATH", str(db_path)), ("DATA_DIR", demo_env.settings.data_dir), ("DEMO_NOW", START)):
        monkeypatch.setenv(key, value)
    assert seed_module.main(["--fresh"]) == 0
    assert not clock_file.exists() and "planned from 2026-10-12" in capsys.readouterr().out


def test_the_demo_route_exists_only_in_a_demo(tmp_path, demo_env):
    off = demo_env.settings.model_copy(update={"demo_now": ""})
    client = TestClient(create_app(off, app_config=demo_env.app_config))
    csrf = login(client)
    assert post(client, "/demo/time", csrf, {"to": "2026-10-15T09:00"}).status_code == 404
    assert "Demo mode" not in client.get("/").text


def test_the_owner_moves_the_demo_clock_and_both_processes_see_it(demo_env):
    env = demo_env
    client = _client(env)
    csrf = login(client)
    assert "Demo mode: it is Mon 12 Oct 2026, 09:00." in client.get("/").text
    assert 'action="/demo/time"' in client.get("/settings").text
    assert post(client, "/demo/time", csrf, {"to": "2026-10-15T09:00"}).status_code == 303
    assert env.clock.now() == at(15, 9)  # the worker's clock, from the same file
    assert "Demo mode: it is Thu 15 Oct 2026, 09:00." in client.get("/").text
    r = post(client, "/demo/time", csrf, {"to": "2026-10-13T09:00"})
    assert r.status_code == 409 and "only moves forward" in r.text
    assert post(client, "/demo/time", csrf, {"to": "next week"}).status_code == 409
    assert env.clock.now() == at(15, 9)


def test_a_helper_cannot_move_the_demo_clock(demo_env):
    client = _client(demo_env)
    csrf = login(client, HELPER)
    assert post(client, "/demo/time", csrf, {"to": "2026-10-15T09:00"}).status_code == 403
    assert demo_env.clock.now() == at(12, 9)


# --- D15: the fixture AI ----------------------------------------------------------------


def test_fixture_ai_needs_demo_mode():
    with pytest.raises(ValidationError, match="DEMO_AI=fixtures is for demos only"):
        Settings(_env_file=None, demo_ai="fixtures")
    assert Settings(_env_file=None, demo_ai="fixtures", demo_now=START).demo_ai == "fixtures"


def test_the_demo_worker_uses_the_fixture_ai_even_with_a_gemini_key(demo_env):
    settings = demo_env.settings.model_copy(update={"demo_ai": "fixtures", "gemini_api_key": "AIza-not-used",
                                                    "test_inbox_path": str(INBOX)})
    backend, config = build_backend(settings, demo_env.app_config)
    assert isinstance(backend, FixtureBackend)
    assert config.model.id == FIXTURE_MODEL == "fixture-ai"
    assert (config.model.pricing.input_micro_usd_per_mtok, config.model.pricing.output_micro_usd_per_mtok) == (0, 0)


def test_an_email_with_no_canned_reply_is_ai_unavailable_never_a_guess():
    backend = FixtureBackend()
    with pytest.raises(AIUnavailable) as e:
        backend.generate(model="fixture-ai", system="s", contents="From: someone@example.test\n\nhello",
                         thinking="medium", json_schema={"title": "SortResult"})
    assert e.value.retryable is False


def test_the_fixture_ai_reads_a_credit_end_to_end_and_says_what_it_is(demo_env):
    env = demo_env
    settings = env.settings.model_copy(update={"demo_ai": "fixtures"})
    backend, config = build_backend(settings, env.app_config)  # replies from fixtures/test_inbox; mail from env's inbox
    env.app_config = config
    env.clock.set(at(16, 11))
    deliver(env, "07-credit-nandi-foods.eml")
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    run_all(env, default_handlers(backend))
    txn = env.conn.execute("SELECT amount_paise, direction, counterparty FROM bank_txn").fetchone()
    assert tuple(txn) == (20_000_000, "credit", "NANDI FOODS")
    assert {r[0] for r in env.conn.execute("SELECT model_id FROM candidate")} == {"fixture-ai"}
    steps = [json.loads(line) for f in Path(env.settings.trace_dir).rglob("*.jsonl")
             for line in f.read_text(encoding="utf-8").splitlines()]
    ai_steps = [s for s in steps if str(s.get("tool", "")).startswith("ai.call")
                and s["input_ref"].startswith("source_document:")]  # the credit's case runs the agent too (S7)
    assert len(ai_steps) == 2
    for s in ai_steps:
        assert s["model"] == "fixture-ai" and s["cost_micro_usd"] == 0
        assert s["tokens"] == {"input": 0, "output": 0, "thoughts": 0}


def test_the_app_says_ai_replies_are_canned(demo_env):
    settings = demo_env.settings.model_copy(update={"demo_ai": "fixtures"})
    client = TestClient(create_app(settings, app_config=demo_env.app_config))
    login(client)
    assert "AI replies are canned fixtures." in client.get("/add").text
