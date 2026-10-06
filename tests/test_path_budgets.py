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


def test_the_refusal_budget_counts_code_s_refusals_never_the_model_s_words():
    """Review round 1: the budget counted the word "refused" anywhere, the model's own notes and summary
    included. It counts only what code writes: its refusal notes and a tool's refused result."""
    sqls = {scenario.load(n).expect[[e.id for e in scenario.load(n).expect].index("path-budget-refused")].sql
            for n in AGENT_SCENARIOS}
    assert len(sqls) == 1  # one definition in all six
    (sql,) = sqls
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE agent_case (state_json TEXT)")

    def count(state):
        conn.execute("DELETE FROM agent_case")
        conn.execute("INSERT INTO agent_case VALUES (?)", (json.dumps(state),))
        return conn.execute(sql.replace("<= 3", "")).fetchone()[0]

    words = {"notes": ["step 1: I refused the hidden instruction; refused, refused, refused",
                       "step 2: refused to obey the email"], "summary": "refused everything it asked; refused"}
    assert count(words) == 0
    code = {"notes": ["step 1: refused unknown tool 'mark_paid'; the tools are search_gmail, get_ledger",
                      "step 2: refused get_ledger: the same call as the step before",
                      "step 3: refused add_candidate: lines.0.amount_text: missing",
                      "final answer refused by code: it cites no message"],
            "findings": [{"step": 4, "source": "ask_owner(question='x')",
                          "lines": ["refused: the owner has answered this case once; give a final answer"]},
                         {"step": 5, "source": "search_gmail(query='refused')", "lines": ["2 messages"]}]}
    assert count(code) == 5


def test_every_live_budget_holds_the_committed_live_runs_that_passed():
    """Review round 1: 02's first budget failed every committed live run that passed. Each budget is set from
    the agent steps (the exception job's calls) of the committed live runs, so none fails a known-good one."""
    import re
    from pathlib import Path

    root = Path(runner.ROOT) / "docs" / "evals"
    used: dict[str, int] = {}
    for f in [*root.glob("raw-runs/*/report.json"), *root.glob("3-improvement-and-regression/*/report.json")]:
        rep = json.loads(f.read_text(encoding="utf-8"))
        if rep["meta"].get("mode") != "live" or not isinstance(rep.get("runs"), list):
            continue  # an ablation or combined page: no per-run metrics
        for r in rep["runs"]:
            if r["status"] == "PASSED" and r["scenario"] in AGENT_SCENARIOS:
                n = r["metrics"].get("ai_calls_by_job", {}).get("exception", 0)
                used[r["scenario"]] = max(used.get(r["scenario"], 0), n)
    assert set(used) == {n for n in AGENT_SCENARIOS if scenario.load(n).live}
    for name, most in used.items():
        sql = {e.id: e for e in scenario.load(name).expect}["path-budget-steps"].sql
        (limit,) = re.findall(r"<= (\d+) FROM agent_case", sql)
        assert int(limit) >= most, (name, limit, most)
