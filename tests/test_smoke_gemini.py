"""`make smoke-gemini` (batch 2 plan, CHG-004 AC8), checked here only with the
fake backend: it makes at most 3 calls, judges the replies with our own
parsing, and does nothing without --yes-call-gemini. The live run itself is
the PO's call and is not part of any test."""

from datetime import datetime

import pytest

from app.ai import smoke
from app.clock import TIMEZONE, FakeClock
from app.config import load_app_config
from app.trace.tracer import Tracer
from tests.fake_ai import FIXTURE_REPLIES, FakeBackend
from tests.worker_helpers import ROOT

CONFIG = load_app_config(ROOT / "config.yaml")
REPLIES = dict(FIXTURE_REPLIES[smoke.DEBIT])
NOTICE = dict(FIXTURE_REPLIES[smoke.RETURN])["FailureNoticeExtract"]


@pytest.fixture
def tracer(tmp_path):
    return Tracer("smoke", tmp_path, FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=TIMEZONE)))


def _backend(alert=None, notice=None):
    return (FakeBackend().queue("SortResult", REPLIES["SortResult"])
            .queue("BankAlertExtract", alert or REPLIES["BankAlertExtract"])
            .queue("FailureNoticeExtract", notice or NOTICE))


def test_good_replies_pass_in_three_calls(tracer, capsys):
    backend = _backend()
    assert smoke.run(backend, CONFIG, tracer) == []
    assert len(backend.requests) == 3
    assert "smoke-gemini: 3 calls" in capsys.readouterr().out


def test_a_misread_amount_is_reported(tracer):
    bad = {**REPLIES["BankAlertExtract"], "amount_text": "Rs.18,000.00"}
    problems = smoke.run(_backend(alert=bad), CONFIG, tracer)
    assert len(problems) == 1 and problems[0].startswith("extract bank_alert: unexpected")


def test_a_reply_that_fails_the_schema_is_reported(tracer):
    problems = smoke.run(_backend(notice="not json"), CONFIG, tracer)
    assert len(problems) == 1 and problems[0].startswith("extract failure_notice:")


def test_the_call_budget_refuses_a_fourth_call():
    budget = smoke.CallBudget(FakeBackend().queue("X", *[{}] * 4))
    for _ in range(3):
        budget.generate(model="m", system="s", contents="c", thinking="low", json_schema={"title": "X"})
    with pytest.raises(RuntimeError, match="at most 3 calls"):
        budget.generate(model="m", system="s", contents="c", thinking="low", json_schema={"title": "X"})


def test_without_the_flag_it_refuses_before_reading_any_settings(monkeypatch, capsys):
    def no_settings(*a, **kw):
        raise AssertionError("Settings must not be read without --yes-call-gemini")

    monkeypatch.setattr(smoke, "Settings", no_settings)
    monkeypatch.setattr(smoke, "GeminiBackend", no_settings)
    assert smoke.main([]) == 2
    assert "pass --yes-call-gemini" in capsys.readouterr().err
