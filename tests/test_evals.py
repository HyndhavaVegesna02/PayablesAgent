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
]


def test_the_suite_has_the_tdd_scenarios():
    assert scenario.names() == TDD_SCENARIOS
