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


# --- S5: the live budget guard (with a fake backend: nothing here calls Gemini) ------------------

from app.ai.client import AIUnavailable, RawAIResponse  # noqa: E402
from evals.budget import BudgetGuard  # noqa: E402


class Priced:
    """A backend that answers with fixed token counts, or raises what it is given."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), 0

    def generate(self, **kw):
        self.calls += 1
        r = self.replies.pop(0) if self.replies else RawAIResponse("{}", 1000, 100, 50)
        if isinstance(r, Exception):
            raise r
        return r


def guard(backend, **kw):
    slept = []
    return BudgetGuard(backend, CONFIG, sleep=slept.append, **kw), slept


def test_the_guard_refuses_the_call_past_the_call_cap():
    g, slept = guard(Priced(), max_calls=3)
    for _ in range(3):
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    with pytest.raises(AIUnavailable) as e:
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert e.value.retryable is False and g.calls == 3 and g.should_stop().startswith("call cap reached: 3 of 3")
    assert slept == [1.0, 1.0]  # paced between calls


def test_the_guard_stops_before_a_call_that_could_pass_the_cost_cap():
    one = RawAIResponse("{}", 1_000_000, 0, 0)  # 1M input tokens at 750,000 micro-USD per Mtok
    g, _ = guard(Priced(one, one, one), max_micro_usd=2_000_000)
    g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert g.micro_usd == 1_500_000
    with pytest.raises(AIUnavailable):  # 1.5M spent + 0.75M for the dearest call so far > 2M
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert g.calls == 2 and "cost cap reached" in g.should_stop()


def test_a_429_backs_off_and_resumes_and_one_that_outlasts_the_backoff_stops():
    rate = AIUnavailable("429", retryable=True, code=429)
    g, slept = guard(Priced(rate, rate, RawAIResponse("{}", 1, 1, 0)), delay_s=0)
    assert g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None).text == "{}"
    assert slept == [5, 10] and g.calls == 3 and g.rate_limited == 2 and g.should_stop() is None
    g, slept = guard(Priced(*[rate] * 6), delay_s=0)
    with pytest.raises(AIUnavailable):
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert slept == [5, 10, 20, 40, 60] and g.should_stop().startswith("rate limited")


def test_other_errors_pass_through_untouched():
    g, _ = guard(Priced(AIUnavailable("503", retryable=True, code=503)))
    with pytest.raises(AIUnavailable) as e:
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert e.value.code == 503 and g.should_stop() is None


def test_a_stopped_guard_ends_the_suite_with_a_partial_aborted_report(tmp_path):
    g, _ = guard(FixtureBackend(), max_calls=6, delay_s=0)
    chosen = [scenario.load(DEBIT), scenario.load("02-password-protected-statement")]
    results, stopped = runner.run_suite(chosen, lambda: g, CONFIG, 2, should_stop=g.should_stop)
    assert stopped.startswith("call cap reached") and g.calls == 6
    assert [r.status for r in results][-1] == "ERRORED" and len(results) < 4
    meta = {"label": "cap", "mode": "live", "model": "m", "prompt_version": "p", "config_sha256": "0" * 64,
            "commit": "c", "date": "d", "runs_per_scenario": 2, "status": "ABORTED", "stopped_because": stopped}
    out = report.write(report.build(meta, chosen, results), tmp_path / "r")
    assert "**ABORTED**: call cap reached" in (out / "report.md").read_text(encoding="utf-8")


def test_live_mode_will_not_start_without_yes_spend():
    from evals.budget import live_backend

    with pytest.raises(SystemExit, match="--yes-spend"):
        live_backend(CONFIG, confirmed=False)


# --- S6: the ablation -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", scenario.names())
def test_the_full_harness_meets_every_outcome_check(name):
    s = scenario.load(name)
    assert s.outcome, f"{name} has no outcome checks for the ablation"
    r = run(s)
    assert r.outcome_ok, [o for o in r.outcomes if not o[1]]


from evals import ablation, bare, knockouts  # noqa: E402


def mechanics():
    return ablation.MechanicsModel(FixtureBackend())


def test_every_knock_out_patches_its_seams_and_restores_them():
    for name in knockouts.KNOCKOUTS:
        patches = knockouts.SEAMS[name](knockouts.Binding())
        before = [getattr(module, attr) for module, attr, _ in patches]
        with knockouts.applied(name, knockouts.Binding()) as seams:
            assert seams and all(getattr(m, a) is not b for (m, a, _), b in zip(patches, before, strict=True))
        assert [getattr(module, attr) for module, attr, _ in patches] == before, name


def test_a_knock_out_is_restored_when_its_run_raises():
    import app.jobs.replan as replan

    real = replan.build_snapshot
    with pytest.raises(RuntimeError), knockouts.applied("no_drift_rule", knockouts.Binding()):
        raise RuntimeError("the run crashed")
    assert replan.build_snapshot is real


def outcome(r, oid):
    return next(ok for i, ok, _ in r.outcomes if i == oid)


def test_without_rule_checks_the_same_invoice_becomes_two_bills():
    s = scenario.load("05-same-invoice-by-email-and-photo")
    r, seams = ablation.run_harness("no_rule_checks", s, FixtureBackend(), CONFIG, 1)
    assert "app.ingest.pipeline.invoice_on_record" in seams
    assert not outcome(r, "one-payable-not-two") and not r.outcome_ok


def test_without_the_drift_rule_the_plan_spends_money_that_may_not_be_there():
    s = scenario.load("08-drift-with-no-explanation")
    r, _ = ablation.run_harness("no_drift_rule", s, FixtureBackend(), CONFIG, 1)
    assert outcome(r, "no-transaction-invented") and not outcome(r, "plan-counts-only-money-that-is-there")


def test_without_escalation_the_agent_runs_on_past_the_rules():
    s = scenario.load("08-drift-with-no-explanation")
    full, _ = ablation.run_harness("full", s, FixtureBackend(), CONFIG, 1)
    cut, _ = ablation.run_harness("no_escalation", s, FixtureBackend(), CONFIG, 1)
    assert full.metrics["escalations"].count("max_steps") == 2  # the run at medium hits its cap, then the rerun at high
    assert cut.metrics["escalations"] == ["max_steps"]  # one run, to the plain cap of 20 steps
    assert cut.metrics["ai_calls_by_job"]["exception"] > full.metrics["ai_calls_by_job"]["exception"]


def test_without_the_planner_the_model_plans_and_the_check_reads_its_plan():
    s = scenario.load("11-shortfall-week")
    r, seams = ablation.run_harness("no_planner", s, mechanics(), CONFIG, 1)
    assert seams == ["app.jobs.replan.plan"]
    assert r.metrics["ai_calls_by_job"]["plan"] >= 1
    assert not r.outcome_ok  # the stand-in planned nothing: Prime Chem is not paid Thursday


def test_the_bare_harness_is_given_the_same_inputs_as_text():
    s = scenario.load("02-password-protected-statement")
    env = bare.BareEnv(None, bare.FakeClock(runner.START))
    said = "\n".join(bare._events(env, s))
    assert "Email arrived (id 10-statement-hdfc-locked.eml)" in said and "read_attachment" in said
    assert "SPW-4821-oct" in said  # the owner's password, as the owner typed it
    assert set(env.emails) == {"10-statement-hdfc-locked.eml"}
    voice = bare._events(bare.BareEnv(None, bare.FakeClock(runner.START)), scenario.load("04-hinglish-voice-note"))
    assert any("voice" in line and "attached" in line for line in voice)


def test_the_bare_harness_runs_its_tools_on_its_own_database_and_is_scored():
    s = scenario.load("08-drift-with-no-explanation")
    r = bare.run_once(s, mechanics(), CONFIG, 1)
    assert r.metrics["ai_calls"] == 2 and r.metrics["tool_calls_by_tool"] == {"list_bills": 1}
    assert [i for i, _, _ in r.outcomes] == [o.id for o in s.outcome]
    assert outcome(r, "no-transaction-invented") and not outcome(r, "plan-counts-only-money-that-is-there")
    assert r.status == "FAILED"


def test_a_bare_write_tool_changes_only_the_scratch_database(tmp_path):
    from app.db.connection import write_connection
    from app.db.migrate import apply_migrations
    from fixtures.seed import seed

    apply_migrations(tmp_path / "b.db")
    conn = write_connection(tmp_path / "b.db")
    seed(conn, bare.FakeClock(runner.START))
    env = bare.BareEnv(conn, bare.FakeClock(runner.START))
    assert bare.TOOLS["record_transaction"](env, {"direction": "debit", "amount": "20,000", "date": "2026-10-13"}) \
        .startswith("transaction")
    assert conn.execute("SELECT amount_paise FROM bank_txn ORDER BY id DESC").fetchone()[0] == 2000000
    assert bare.TOOLS["set_bill_status"](env, {"bill_id": 999, "status": "PAID"}) == "no such record"


def test_a_bare_step_is_one_tool_call_or_a_final_answer():
    with pytest.raises(ValidationError):
        bare.BareStep(notes="", tool=None, final=None)
    with pytest.raises(ValidationError):
        bare.BareStep(tool=bare.BareTool(name="list_bills"), final=bare.BareFinal(lowest_balance_text="Rs.0"))


def test_the_ablation_report_states_the_fair_comparison_and_names_the_biggest_drop(tmp_path):
    names = ["05-same-invoice-by-email-and-photo", "08-drift-with-no-explanation"]
    chosen = [scenario.load(n) for n in names]
    results, seams = {}, {}
    for h in ("full", "bare", "no_rule_checks", "no_drift_rule"):
        results[h] = []
        for s in chosen:
            r, seams[h] = ablation.run_harness(h, s, mechanics(), CONFIG, 1)
            results[h].append(r)
    meta = {"label": "t", "mode": "fixtures", "model": "fixture-ai", "prompt_version": "v", "config_sha256": "0" * 64,
            "commit": "abc1234", "date": "2026-10-03T00:00:00+05:30", "runs_per_scenario": 1, "status": "COMPLETE"}
    built = ablation.build(meta, list(results), chosen, results, seams)
    assert built["harnesses"]["full"]["outcome_success_rate"] == 1.0
    assert built["drops"] == {"no_rule_checks": 0.5, "no_drift_rule": 0.5}  # bare is never a knock-out
    assert built["harnesses"]["bare"]["mechanics_only"] and not built["harnesses"]["no_drift_rule"]["mechanics_only"]
    md = ablation.write(built, chosen, tmp_path).joinpath("report.md").read_text(encoding="utf-8")
    assert "(D24)" in md and "the same inputs" in md and "the model is the same" in md
    assert "Only the harness differs." in md and "*mechanics only*" in md
    assert "Knocking out **no_drift_rule, no_rule_checks** cost the most" in md
    assert "abc1234" in md and "`app.jobs.replan.build_snapshot`" in md


def test_make_ablation_is_no_longer_a_stub():
    text = (runner.ROOT / "Makefile").read_text(encoding="utf-8")
    assert "python -m evals.ablation" in text and "not yet implemented" not in text.split("ablation:")[-1]
