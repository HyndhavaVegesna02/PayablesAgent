"""The eval system (batch 7, CHG-010a). The runner plays a scenario on a fresh
seeded copy through the real worker and scores it; a failed check names its
component, earliest in pipeline order first; a crash fails the run, and a
stop hook (the budget guard) errors it."""

import pytest
from pydantic import ValidationError

from app.ai.fixture_backend import FixtureBackend
from app.config import load_app_config
from evals import runner, scenario
from evals.scenario import Expectation, Scenario

CONFIG = load_app_config(runner.ROOT / "config.yaml")
DEBIT = "01-debit-alert-for-a-planned-payment"


def run(s, **kw):
    return runner.run_once(s, FixtureBackend(), CONFIG, **kw)


def test_a_scenario_runs_through_the_worker_and_passes():
    r = run(scenario.load(DEBIT))
    assert r.status == "PASSED" and r.component is None and r.met == 1.0
    assert {c.component for c in r.checks} >= {"sort", "extract", "validate", "reconcile", "planner"}


def test_a_failed_check_names_the_earliest_component_that_broke():
    s = scenario.load(DEBIT)
    wrong = [e.model_copy(update={"equals": "UNMATCHED"}) if e.id == "debit-matched" else e for e in s.expect]
    wrong.append(Expectation(id="late", component="planner", sql="SELECT 1", equals=2))
    r = run(s.model_copy(update={"expect": wrong}))
    assert (r.status, r.component) == ("FAILED", "reconcile")  # reconcile comes before planner
    assert [c.id for c in r.checks if not c.ok] == ["debit-matched", "late"]


def test_a_crash_fails_the_run_and_a_stop_hook_errors_it():
    s = scenario.load(DEBIT)
    crash = s.model_copy(update={"steps": [{"confirm_balance": {"amount": "5,00,000"}}]})  # nothing to confirm
    r = run(crash)
    assert (r.status, r.component) == ("FAILED", "crash") and "Refused" in r.error
    r = run(s, should_stop=lambda: "budget: 600 calls used")
    assert (r.status, r.error) == ("ERRORED", "budget: 600 calls used")


def test_a_scenario_file_is_checked():
    base = {"name": "x", "title": "x", "passes_when": "x", "steps": [{"poll": True}],
            "expect": [{"id": "a", "component": "sort", "sql": "SELECT 1", "equals": 1}]}
    Scenario.model_validate(base)
    with pytest.raises(ValidationError):
        Scenario.model_validate({**base, "steps": [{"pay_bill": 1}]})
    with pytest.raises(ValidationError):
        Scenario.model_validate({**base, "expect": [{"id": "a", "component": "sort", "sql": "DELETE FROM payable",
                                                     "equals": 1}]})
    with pytest.raises(ValidationError):
        Scenario.model_validate({**base, "expect": [{"id": "a", "component": "gemini", "sql": "SELECT 1",
                                                     "equals": 1}]})


@pytest.mark.parametrize("name", scenario.names())
def test_every_scenario_passes_in_fixture_mode(name):
    r = run(scenario.load(name))
    assert r.status == "PASSED", [(c.id, c.got, c.want) for c in r.checks if not c.ok] or r.error


def test_scenario_folders_hold_inputs_and_expectations_but_no_replies():
    for name in scenario.names():
        folder = scenario.SCENARIOS / name
        for f in folder.iterdir():
            assert f.name == "expected.yaml" or f.suffix in {".eml", ".png", ".pdf", ".wav"}, f
        assert "Extract" not in (folder / "expected.yaml").read_text(encoding="utf-8")  # no canned model reply


TDD_SCENARIOS = [  # TDD Part 1, "Scenario suite (test inbox and uploads)", in its order
    "01-debit-alert-for-a-planned-payment",
    "02-password-protected-statement",
    "03-handwritten-bill-photo",
    "04-hinglish-voice-note",
    "05-same-invoice-by-email-and-photo",
    "06-payment-returned-by-the-bank",
    "07-missed-alert-causes-drift",
    "08-drift-with-no-explanation",
    "09-vendor-email-changes-bank-details",
    "10-hidden-instruction-in-a-vendor-email",
    "11-shortfall-week",
]


def test_the_suite_has_the_tdd_scenarios():
    assert scenario.names() == TDD_SCENARIOS


# --- S4: metrics and the report ----------------------------------------------------------------

from evals import metrics, report  # noqa: E402
from evals.runner import Check, RunResult  # noqa: E402


def test_the_trajectory_is_counted_from_the_runs_own_trace_and_jobs():
    r = runner.run_once(scenario.load("07-missed-alert-causes-drift"), FixtureBackend(), CONFIG,
                        inspect=metrics.inspect)
    m = r.metrics
    assert m["ai_calls"] == sum(m["ai_calls_by_job"].values()) and m["ai_calls_by_job"]["exception"] >= 3
    assert m["tool_calls_by_tool"]["search_gmail"] >= 1 and m["tool_calls_by_tool"]["add_candidate"] >= 1
    # the follow-up case's two failed candidates end its medium run; its high run hits the step limit
    assert m["invalid_candidates"] == 2 and m["wasted_calls"] >= 2
    assert set(m["escalations"]) == {"max_validation_failures", "max_steps"}
    assert m["tokens"] == {"input": 0, "output": 0, "thoughts": 0} and m["cost_micro_usd"] == 0  # fixture replies


def test_the_trace_fields_the_metrics_read_are_the_ones_the_code_writes():
    steps = []
    r = runner.run_once(scenario.load("08-drift-with-no-explanation"), FixtureBackend(), CONFIG,
                        inspect=lambda env: steps.extend(metrics.trace_steps(env.settings.trace_dir)) or {})
    assert r.status == "PASSED"
    ai = next(s for s in steps if str(s.get("tool")).startswith("ai.call"))
    assert {"validation", "tokens", "cost_micro_usd"} <= set(ai)
    assert any(s.get("tool") == "escalation" and s.get("escalation_rule") == "max_steps" for s in steps)
    assert any(str(s.get("tool")).startswith("agent:") and "result" in s for s in steps)


def _result(name, run, status, met_ok, cost=0, component=None):
    checks = [Check(f"c{i}", "reconcile", ok, None, None) for i, ok in enumerate(met_ok)]
    return RunResult(name, run, status, checks, component, None,
                     {"ai_calls": 2, "cost_micro_usd": cost, "tokens": {"input": 10, "output": 5, "thoughts": 1},
                      "escalations": []})


def test_the_report_gives_rate_spread_worst_run_and_keeps_errored_runs_apart():
    s = scenario.load(DEBIT)
    runs = [_result(DEBIT, 1, "PASSED", [True, True], 100), _result(DEBIT, 2, "FAILED", [True, False], 300, "reconcile"),
            _result(DEBIT, 3, "PASSED", [True, True], 200), _result(DEBIT, 4, "ERRORED", [], 0)]
    row = report.aggregate(s, runs)
    assert (row["passed"], row["failed"], row["errored"], row["success_rate"]) == (2, 1, 1, 0.667)
    assert row["spread"] == [0.5, 1.0] and row["worst"]["run"] == 2 and row["worst"]["component"] == "reconcile"
    assert row["cost_micro_usd"] == {"mean": 200.0, "max": 300}
    meta = {"label": "t", "mode": "live", "model": "m", "prompt_version": "p", "config_sha256": "0" * 64,
            "commit": "abc", "date": "d", "runs_per_scenario": 4, "status": "ABORTED",
            "stopped_because": "budget: 600 calls used"}
    md = report.markdown(report.build(meta, [s], runs))
    assert md.startswith("# Eval report: t") and "**ABORTED**: budget: 600 calls used" in md
    assert "| Bank debit alert for a planned payment | 2/3 (67%), 1 errored | 50% – 100% | run 2: reconcile, 1 failed |" in md
