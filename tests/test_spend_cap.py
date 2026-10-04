"""A 429 for Gemini's monthly spending cap is permanent (CHG-040). Waiting
can't help with it, so the job queue gives up at once and the eval guard stops
the invocation, naming the cap; a rate-limit 429 still backs off and retries.
GeminiBackend runs offline here, on httpx.MockTransport."""

import httpx
import pytest

from app.ai.client import AIUnavailable, GeminiBackend, RawAIResponse
from evals.budget import BudgetGuard
from tests.test_evals import CONFIG

SPEND_CAP = ("Your project has exceeded its monthly spending cap. Please go to AI Studio at "
             "https://ai.studio/spend to manage your project spend cap.")
RATE_LIMIT = ("You exceeded your current quota, please check your plan and billing details. For more information "
              "on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits.")


def _backend(message, details=None):
    error = {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED"}
    if details is not None:
        error["details"] = details
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(429, json={"error": error})))
    return GeminiBackend("fake-key-for-tests", timeout_ms=1000, httpx_client=client)


def _generate(backend):
    return backend.generate(model="gemini-3.8-flash", system="s", contents="c", thinking="low", json_schema=None)


@pytest.mark.parametrize("message, details", [
    (SPEND_CAP, None),
    ("Your prepayment credits are depleted. Please go to AI Studio to add credits.", None),
    ("Spend cap exceeded for this project.", None),
    ("Resource has been exhausted.", [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                       "reason": "SPENDING_CAP_EXCEEDED", "domain": "googleapis.com"}]),
    ("Resource has been exhausted.", [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                       "reason": "BILLING_DISABLED", "domain": "googleapis.com"}]),
])
def test_a_spend_cap_429_is_permanent(message, details):
    with pytest.raises(AIUnavailable) as e:
        _generate(_backend(message, details))
    assert (e.value.code, e.value.retryable) == (429, False)


@pytest.mark.parametrize("message, details", [
    (RATE_LIMIT, None),  # names "billing details", but is the per-minute or per-day quota
    ("Resource has been exhausted (e.g. check quota).", [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaMetric": "requests"}]},
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMIT_EXCEEDED"}]),
])
def test_a_rate_limit_429_stays_retryable(message, details):
    with pytest.raises(AIUnavailable) as e:
        _generate(_backend(message, details))
    assert (e.value.code, e.value.retryable) == (429, True)


class Once:
    def __init__(self, backend):
        self.backend, self.calls = backend, 0

    def generate(self, **kw):
        self.calls += 1
        return self.backend.generate(**kw)


def test_the_guard_stops_at_once_on_the_spend_cap_and_names_it():
    slept = []
    inner = Once(_backend(SPEND_CAP))
    g = BudgetGuard(inner, CONFIG, sleep=slept.append, delay_s=0)
    with pytest.raises(AIUnavailable) as e:
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert e.value.retryable is False and inner.calls == 1 and slept == []  # no backoff
    assert g.should_stop().startswith("spend cap: Google refused the call (429)")
    assert "monthly spending cap" in g.should_stop()
    with pytest.raises(AIUnavailable):  # and every later call is refused without reaching Google
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert inner.calls == 1 and g.summary()["stopped"] == g.should_stop()


def test_the_guard_still_backs_off_on_a_rate_limit_429():
    slept = []
    replies = [AIUnavailable("429", retryable=True, code=429), RawAIResponse("{}", 1, 1, 0)]

    class Flaky:
        def generate(self, **kw):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

    g = BudgetGuard(Flaky(), CONFIG, sleep=slept.append, delay_s=0)
    assert g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None).text == "{}"
    assert slept == [5] and g.should_stop() is None
