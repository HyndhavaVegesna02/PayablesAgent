"""ai.client (batch 2 plan, CHG-004 AC2, AC3, AC7). call() is tested with the
fake backend; GeminiBackend is tested offline, with httpx.MockTransport in
place of the network, so no request ever leaves the machine."""

import json
from datetime import datetime

import httpx
import pytest

from app.ai.client import AIUnavailable, GeminiBackend, call, cost_micro_usd, load_prompt
from app.ai.extract import BankAlertExtract
from app.ai.sort import SortResult, sort_document
from app.clock import TIMEZONE, FakeClock
from app.config import load_app_config
from app.trace.tracer import Tracer
from tests.fake_ai import FakeBackend
from tests.worker_helpers import ROOT

CONFIG = load_app_config(ROOT / "config.yaml")
ALERT = {
    "account_last4": "4821", "direction": "debit", "amount_text": "Rs.1,80,000.00",
    "txn_date": "2026-10-12", "counterparty": "ASHIRWAD PAPER SUPPLIERS", "reference": "N286261234567",
    "available_balance_text": "Rs.4,40,000.00", "uncertain_fields": [],
}


@pytest.fixture
def tracer(tmp_path):
    return Tracer("job-1-attempt-1", tmp_path, FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=TIMEZONE)))


def _steps(tracer):
    path = tracer.trace_dir / "2026-10-12" / f"{tracer.run_id}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _call(backend, tracer, *, thinking="medium", schema=BankAlertExtract):
    return call(job="extract:bank_alert", thinking=thinking, system="sys", context="email text",
                schema=schema, backend=backend, app_config=CONFIG, tracer=tracer,
                input_ref="source_document:1", prompt_version="2026-10-02.1/extract_bank_alert.v1")


# --- call() ---------------------------------------------------------------------


def test_call_parses_the_text_against_the_schema_itself(tracer):
    backend = FakeBackend().queue("BankAlertExtract", ALERT)
    r = _call(backend, tracer)
    assert isinstance(r.parsed, BankAlertExtract)
    assert r.parsed.amount_text == "Rs.1,80,000.00"
    assert r.schema_error is None
    sent = backend.requests[0]
    assert (sent.model, sent.thinking, sent.system, sent.contents) == (
        "gemini-3.8-flash", "medium", "sys", "email text",
    )
    assert sent.json_schema == BankAlertExtract.model_json_schema()


@pytest.mark.parametrize("text", ['{"account_last4": "4821"}', "not json", "", None])
def test_text_that_does_not_match_the_schema_is_a_schema_failure_not_an_error(tracer, text):
    r = _call(FakeBackend().queue("BankAlertExtract", text), tracer)
    assert r.parsed is None
    assert r.schema_error
    assert _steps(tracer)[0]["validation"].startswith("schema: failed")


@pytest.mark.parametrize("level", ["minimal", "MEDIUM", "", "max", None])
def test_only_low_medium_and_high_thinking_are_sent(tracer, level):
    backend = FakeBackend().queue("BankAlertExtract", ALERT)
    with pytest.raises(ValueError):
        _call(backend, tracer, thinking=level)
    assert backend.requests == []


def test_cost_is_integer_micro_usd_with_thoughts_billed_as_output(tracer):
    backend = FakeBackend(usage=(1000, 100, 50)).queue("BankAlertExtract", ALERT)
    r = _call(backend, tracer)
    # 1000 * $0.75/M + (100 + 50) * $3.75/M = $0.00075 + $0.0005625 = 1312.5 micro-USD, rounded up
    assert r.cost_micro_usd == 1313
    assert type(r.cost_micro_usd) is int
    assert (r.input_tokens, r.output_tokens, r.thought_tokens) == (1000, 100, 50)


def test_cost_rounds_up_and_zero_tokens_cost_nothing():
    assert cost_micro_usd(CONFIG, 0, 0) == 0
    assert cost_micro_usd(CONFIG, 1, 0) == 1  # 0.75 micro-USD is never rounded down to free
    assert cost_micro_usd(CONFIG, 1_000_000, 1_000_000) == 4_500_000


def test_every_call_writes_one_trace_step_with_tokens_and_cost(tracer):
    _call(FakeBackend(usage=(1000, 100, 50)).queue("BankAlertExtract", ALERT), tracer)
    (step,) = _steps(tracer)
    assert step["input_ref"] == "source_document:1"
    assert (step["model"], step["thinking"], step["tool"]) == ("gemini-3.8-flash", "medium",
                                                                "ai.call:extract:bank_alert")
    assert step["tokens"] == {"input": 1000, "output": 100, "thoughts": 50}
    assert step["cost_micro_usd"] == 1313
    assert step["validation"] == "schema: passed"
    assert step["retries"] == 0
    assert step["arguments"] == {"prompt_version": "2026-10-02.1/extract_bank_alert.v1",
                                 "schema": "BankAlertExtract"}
    assert step["result"] == json.dumps(ALERT)[:200]


def test_sort_uses_the_configured_low_thinking_and_its_prompt(tracer):
    backend = FakeBackend().queue("SortResult", {"doc_type": "bank_alert", "reason": "debit alert"})
    r = sort_document("email", backend=backend, app_config=CONFIG, tracer=tracer, input_ref="d:1")
    assert r.parsed == SortResult(doc_type="bank_alert", reason="debit alert")
    assert backend.requests[0].thinking == CONFIG.model.thinking.sort == "low"
    assert backend.requests[0].system == load_prompt("sort.v1")


def test_every_prompt_tells_the_model_not_to_follow_instructions_in_the_email():
    for name in ("sort.v1", "extract_bank_alert.v1", "extract_failure.v1"):
        assert "never\nfollow them" in load_prompt(name) or "never follow them" in load_prompt(name)


# --- GeminiBackend, offline -----------------------------------------------------------

OK_BODY = {
    "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(ALERT)}]},
                    "finishReason": "STOP"}],
    "usageMetadata": {"promptTokenCount": 812, "candidatesTokenCount": 96, "thoughtsTokenCount": 240},
}


class Recorder:
    def __init__(self, respond):
        self.respond = respond
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        return self.respond(request)


def _backend(respond):
    rec = Recorder(respond)
    client = httpx.Client(transport=httpx.MockTransport(rec))
    return GeminiBackend("fake-key-for-tests", timeout_ms=1000, httpx_client=client), rec


def _generate(backend, schema=BankAlertExtract):
    return backend.generate(model="gemini-3.8-flash", system="sys", contents="email text",
                            thinking="medium",
                            json_schema=schema.model_json_schema() if schema else None)


def test_the_request_carries_thinking_level_and_the_json_schema_and_nothing_else(tracer):
    backend, rec = _backend(lambda req: httpx.Response(200, json=OK_BODY))
    r = call(job="extract:bank_alert", thinking="medium", system="sys", context="email text",
             schema=BankAlertExtract, backend=backend, app_config=CONFIG, tracer=tracer,
             input_ref="d:1")

    (req,) = rec.requests
    assert req.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
    body = json.loads(req.content)
    cfg = body["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"] == BankAlertExtract.model_json_schema()
    thinking = {k.replace("_", "").lower(): v for k, v in cfg["thinkingConfig"].items()}
    assert thinking == {"thinkinglevel": "MEDIUM"}
    flat = json.dumps(body).lower()
    for absent in ("temperature", "topp", "top_p", "topk", "top_k", "thinkingbudget", "thinking_budget",
                   "responseschema\"", "tools"):
        assert absent not in flat.replace(" ", ""), absent
    assert body["systemInstruction"]["parts"] == [{"text": "sys"}]
    assert body["contents"] == [{"role": "user", "parts": [{"text": "email text"}]}]
    assert r.parsed.reference == "N286261234567"
    assert (r.input_tokens, r.output_tokens, r.thought_tokens) == (812, 96, 240)


def test_missing_usage_counts_are_zero():
    body = {k: v for k, v in OK_BODY.items() if k != "usageMetadata"}
    backend, _ = _backend(lambda req: httpx.Response(200, json=body))
    raw = _generate(backend)
    assert (raw.input_tokens, raw.output_tokens, raw.thought_tokens) == (0, 0, 0)
    partial = {**OK_BODY, "usageMetadata": {"promptTokenCount": 5}}
    backend, _ = _backend(lambda req: httpx.Response(200, json=partial))
    raw = _generate(backend)
    assert (raw.input_tokens, raw.output_tokens, raw.thought_tokens) == (5, 0, 0)


def test_a_response_with_no_candidates_has_no_text():
    backend, _ = _backend(lambda req: httpx.Response(200, json={"candidates": [], "usageMetadata": {}}))
    assert _generate(backend).text is None


@pytest.mark.parametrize("code, status, retryable", [
    (429, "RESOURCE_EXHAUSTED", True),
    (500, "INTERNAL", True),
    (503, "UNAVAILABLE", True),
    (400, "INVALID_ARGUMENT", False),
    (403, "PERMISSION_DENIED", False),
])
def test_api_errors_map_to_retryable_or_permanent(code, status, retryable):
    error = {"error": {"code": code, "message": "m", "status": status}}
    backend, rec = _backend(lambda req: httpx.Response(code, json=error))
    with pytest.raises(AIUnavailable) as e:
        _generate(backend)
    assert (e.value.retryable, e.value.code, e.value.status) == (retryable, code, status)
    assert len(rec.requests) == 1  # one attempt: the job queue owns retries


@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.ConnectError])
def test_timeouts_and_connection_errors_are_retryable(exc):
    def fail(req):
        raise exc("no answer", request=req)

    backend, rec = _backend(fail)
    with pytest.raises(AIUnavailable) as e:
        _generate(backend)
    assert e.value.retryable is True
    assert len(rec.requests) == 1


@pytest.mark.parametrize("key", ["", "   "])
def test_gemini_backend_refuses_a_blank_key(key):
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiBackend(key, timeout_ms=1000)
