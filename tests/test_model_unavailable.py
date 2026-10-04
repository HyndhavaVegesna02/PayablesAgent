"""CHG-053: a model that was unavailable never scores as a harness failure.
Live ablation v2 ran on after Gemini's prepaid credits ran out (every call a
402), and its knock-outs scored those runs FAILED at zero cost. The budget
guard now stops on a permanent billing refusal, and a run whose model was
unavailable is ERRORED, never FAILED, and counts in no success rate."""

import json

from app.ai.client import AIUnavailable
from app.ai.fixture_backend import FixtureBackend
from evals import ablation, budget, metrics, runner, scenario

CONFIG = runner.load_config(None)[0]
FIRST = "01-debit-alert-for-a-planned-payment"
SECOND = "02-password-protected-statement"


class CreditsRunOut(FixtureBackend):
    """Canned replies for the first `left` calls, then Google's 402 for every call."""

    def __init__(self, left: int) -> None:
        super().__init__()
        self.left = left

    def generate(self, **kwargs):
        if self.left <= 0:
            raise AIUnavailable("Gemini refused the request: 402 RESOURCE_EXHAUSTED", retryable=False, code=402,
                                status="RESOURCE_EXHAUSTED", detail="Your prepayment credits are depleted.")
        self.left -= 1
        return super().generate(**kwargs)


def _guard(left):
    return budget.BudgetGuard(CreditsRunOut(left), CONFIG, delay_s=0, sleep=lambda s: None)


def test_the_guard_stops_the_invocation_on_a_402_and_names_it():
    guard = _guard(0)
    for _ in range(2):
        try:
            guard.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
        except AIUnavailable as e:
            assert not e.retryable
    assert guard.stopped and "402" in guard.stopped and "credit" in guard.stopped.lower()
    assert guard.calls == 1  # the second call was refused by the guard, not sent


def test_a_402_mid_suite_errors_the_run_and_stops_the_suite():
    guard = _guard(1)  # the first call answers; the second meets the 402
    results, stopped = runner.run_suite([scenario.load(FIRST), scenario.load(SECOND)], lambda: guard, CONFIG, 1,
                                        should_stop=guard.should_stop)
    assert [r.status for r in results] == ["ERRORED"]  # never FAILED; the second scenario never starts
    assert stopped and "402" in stopped


def test_a_402_mid_ablation_errors_the_run_and_it_counts_in_no_rate(tmp_path, monkeypatch):
    guard = _guard(1)
    monkeypatch.setattr(budget, "live_backend", lambda *a, **k: guard)
    code = ablation.main(["--ai", "live", "--yes-spend", "--harness", "full", "--harness", "no_rule_checks",
                          "--scenario", FIRST, "--scenario", SECOND, "--label", "t", "--out", str(tmp_path)])
    assert code == 1  # ABORTED
    (out,) = tmp_path.glob("*-live-t")
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["meta"]["status"] == "ABORTED" and "402" in rep["meta"]["stopped_because"]
    assert [r["status"] for r in rep["runs"]["full"]] == ["ERRORED"] and rep["runs"]["no_rule_checks"] == []
    assert rep["harnesses"]["full"]["outcome_success_rate"] is None  # nothing scored, so no rate
    assert rep["drops"] == {}


def test_without_a_guard_a_run_whose_model_was_unavailable_is_errored_not_failed():
    """The product's pipeline catches AIUnavailable and carries on; the run used to end FAILED on its checks."""
    r = runner.run_once(scenario.load(FIRST), CreditsRunOut(1), CONFIG, 1, inspect=metrics.inspect)
    assert r.status == "ERRORED" and "model was unavailable" in r.error and "402" in r.error
    assert not r.outcome_ok


def _trace(d, name, validation):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"tool": "ai.call:sort", "validation": validation}) + "\n", encoding="utf-8")


def test_a_retryable_failure_a_later_attempt_recovered_from_is_not_unavailability(tmp_path):
    _trace(tmp_path / "2026-10-12", "job-2-attempt-1.jsonl", "not run: AI unavailable (retryable, 503): busy")
    _trace(tmp_path / "2026-10-12", "job-2-attempt-2.jsonl", "schema: passed")
    assert metrics.model_unavailable(tmp_path) is None
    _trace(tmp_path / "2026-10-13", "job-5-attempt-1.jsonl", "not run: AI unavailable (retryable, 503): busy")
    assert "503" in metrics.model_unavailable(tmp_path)  # the job's last attempt still had no model
    _trace(tmp_path / "2026-10-13", "job-5-attempt-2.jsonl", "schema: passed")
    _trace(tmp_path / "2026-10-13", "knockout-no_planner.jsonl", "not run: AI unavailable (permanent, 402): x")
    assert "402" in metrics.model_unavailable(tmp_path)


def test_the_fixture_ai_s_missing_canned_reply_is_not_a_model_that_was_down(tmp_path):
    """The plan's "what changed" note has no canned reply by design (D15): fixture runs stay scored."""
    _trace(tmp_path, "job-9-attempt-1.jsonl",
           "not run: AI unavailable (permanent, None): the demo fixture AI has no canned PlanSummary for this document")
    assert metrics.model_unavailable(tmp_path) is None
    assert runner.run_once(scenario.load(FIRST), FixtureBackend(), CONFIG, 1).status == "PASSED"
