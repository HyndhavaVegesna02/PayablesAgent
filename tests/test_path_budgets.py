"""Path budgets (CHG-050): every scenario whose run opens an agent case
asserts trajectory limits (the agent's steps, and calls code refused), and
they apply live too, so trajectory checks are not just 07's."""

import json
import sqlite3

import pytest

from app.ai.fixture_backend import FixtureBackend
from evals import runner, scenario

CONFIG = runner.load_config(None)[0]
AGENT_SCENARIOS = ["02-password-protected-statement", "07-missed-alert-causes-drift",
                   "08-drift-with-no-explanation", "10-hidden-instruction-in-a-vendor-email",
                   "13-one-debit-two-same-amount-bills", "14-noisy-statement-row"]


def test_the_agent_scenarios_are_exactly_the_ones_that_open_agent_cases():
    opened = []
    for name in scenario.names():
        seen = {}

        def count(env, seen=seen):
            seen["n"] = env.conn.execute("SELECT COUNT(*) FROM agent_case").fetchone()[0]
            return {}

        runner.run_once(scenario.load(name), FixtureBackend(), CONFIG, 1, inspect=count)
        if seen["n"]:
            opened.append(name)
    assert opened == AGENT_SCENARIOS


@pytest.mark.parametrize("name", AGENT_SCENARIOS)
def test_every_agent_scenario_has_both_budgets_and_they_apply_live(name):
    checks = {e.id: e for e in scenario.load(name).expect}
    for cid in ("path-budget-steps", "path-budget-refused"):
        assert checks[cid].level == "trajectory" and not checks[cid].fixtures_only, (name, cid)


def test_a_budget_fails_when_the_agent_wastes_calls():
    refused = {e.id: e for e in scenario.load(AGENT_SCENARIOS[0]).expect}["path-budget-refused"].sql
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE agent_case (state_json TEXT)")
    notes = [f"step {i}: refused get_ledger: bad account" for i in range(4)]
    conn.execute("INSERT INTO agent_case VALUES (?)", (json.dumps({"notes": notes}),))
    assert conn.execute(refused).fetchone()[0] == 0
