"""What a trace records about time and attempts (CHG-047). The business
clock (`timestamp`, the injected Clock) says when in the story a step
happened; `wall_time` (a SystemClock) says when it really ran, so an AI call
also carries `latency_ms`. `attempt` is the job's attempt number and
`retries` the backend's own retries for that call, never a hard-coded 0. A
reply is kept to 2,000 characters."""

import json
from datetime import datetime

from app.ai.client import AIUnavailable, RawAIResponse, call
from app.clock import FakeClock
from app.trace.tracer import Tracer
from evals.budget import BudgetGuard
from tests.test_evals import CONFIG

STORY = datetime.fromisoformat("2026-10-12T09:00:00+05:30")


def _lines(tmp_path):
    return [json.loads(line) for f in sorted(tmp_path.rglob("*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines()]


class Slow:
    """A backend that answers a long reply; `last_retries` is what it says it retried."""

    def __init__(self, last_retries=0):
        self.last_retries = last_retries

    def generate(self, **kw):
        return RawAIResponse("x" * 5000, 10, 5, 0)


def test_a_step_has_wall_time_beside_the_business_clock(tmp_path):
    tracer = Tracer("job-1-attempt-1", tmp_path, FakeClock(STORY))
    tracer.step(tool="poll_mail")
    (line,) = _lines(tmp_path)
    assert line["timestamp"] == STORY.isoformat()
    wall = datetime.fromisoformat(line["wall_time"])
    assert wall.tzinfo is not None and wall.year >= 2026 and wall != STORY


def test_an_ai_call_records_latency_attempt_retries_and_up_to_2000_characters(tmp_path):
    tracer = Tracer("job-7-attempt-3", tmp_path, FakeClock(STORY))
    tracer.attempt = 3
    call(job="sort", thinking="low", system="s", context="c", schema=None, backend=Slow(last_retries=2),
         app_config=CONFIG, tracer=tracer, input_ref="d:1")
    (line,) = _lines(tmp_path)
    assert type(line["latency_ms"]) is int and line["latency_ms"] >= 0
    assert (line["attempt"], line["retries"]) == (3, 2)
    assert len(line["result"]) == 2000


def test_a_failed_call_records_them_too(tmp_path):
    class Down:
        last_retries = 5

        def generate(self, **kw):
            raise AIUnavailable("down", retryable=True, code=503)

    tracer = Tracer("job-2-attempt-1", tmp_path, FakeClock(STORY))
    tracer.attempt = 1
    try:
        call(job="sort", thinking="low", system="s", context="c", schema=None, backend=Down(),
             app_config=CONFIG, tracer=tracer, input_ref="d:1")
    except AIUnavailable:
        pass
    (line,) = _lines(tmp_path)
    assert (line["attempt"], line["retries"]) == (1, 5) and type(line["latency_ms"]) is int


def test_the_guard_reports_the_429_retries_it_made_for_the_last_call():
    rate = AIUnavailable("429", retryable=True, code=429)
    replies = [rate, rate, RawAIResponse("{}", 1, 1, 0), RawAIResponse("{}", 1, 1, 0)]

    class Flaky:
        def generate(self, **kw):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

    g = BudgetGuard(Flaky(), CONFIG, sleep=lambda s: None, delay_s=0)
    g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert g.last_retries == 2
    g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert g.last_retries == 0


def test_the_worker_tells_its_tracer_the_attempt(tmp_path):
    from app.jobs import queue
    from app.worker import process_one
    from tests.worker_helpers import make_env

    env = make_env(tmp_path)
    seen = []

    def flaky(ctx):
        seen.append(ctx.tracer.attempt)
        if len(seen) == 1:
            raise RuntimeError("first attempt fails")

    queue.enqueue(env.conn, kind="probe", payload={}, clock=env.clock)
    env.conn.commit()
    for _ in range(2):
        env.clock.advance(__import__("datetime").timedelta(hours=1))  # past the retry's backoff
        process_one(env.conn, {"probe": flaky}, clock=env.clock, settings=env.settings, app_config=env.app_config)
    assert seen == [1, 2]


def test_an_ablation_keeps_every_harness_traces_bare_included(tmp_path):
    """CHG-047: the bare harness used to delete its traces; a live ablation (or --keep-traces) keeps them."""
    from evals import ablation

    ablation.main(["--ai", "fixtures", "--harness", "bare", "--harness", "full", "--scenario",
                   "06-payment-returned-by-the-bank", "--label", "t", "--keep-traces", "--out", str(tmp_path)])
    (out,) = tmp_path.glob("*-fixtures-t")
    assert sorted(p.name for p in (out / "traces").iterdir()) == ["bare", "full"]
    for h in ("bare", "full"):  # one layout for every harness: traces/<harness>/<scenario>-run<n>/<date>/
        (run,) = (out / "traces" / h).iterdir()
        assert run.name == "06-payment-returned-by-the-bank-run1"
        assert all(d.is_dir() and d.name[:4].isdigit() for d in run.iterdir())
        assert list(run.rglob("*.jsonl"))
