"""run_case (batch 6, CHG-008, S5): one call per step with the case file;
tool calls checked by code; escalation counted in code; a stopped run
resumes at its step; a repeated call is refused."""

from datetime import timedelta

import pytest

from app.agent import cases, escalation
from app.agent.loop import Deps, run_case
from app.ingest.eml_folder import EmlFolderSource
from app.ingest.store import DocumentStore
from tests.agent_helpers import open_unknown_debit_case
from tests.fake_ai import FakeBackend
from tests.worker_helpers import deliver, make_mail_env

FINAL = {"outcome": "NEEDS_OWNER", "summary": "Nothing found.", "cited_message_ids": [],
         "relied_on_candidate_ids": []}


def search(q, notes="looking"):
    return {"notes": notes, "tool": {"name": "search_gmail", "args": {"query": q}}}


@pytest.fixture
def env(tmp_path):
    e = make_mail_env(tmp_path)
    e.clock.advance(timedelta(days=2, hours=3))
    deliver(e, "09-invoice-ashirwad-new-bank.eml")
    yield e
    e.conn.close()


def deps(env, backend):
    from app.trace.tracer import Tracer

    return Deps(backend, env.app_config, Tracer("run-1", env.settings.trace_dir, env.clock),
                EmlFolderSource(env.settings.test_inbox_path, env.clock), env.clock, env.settings.database_path,
                DocumentStore(env.settings.data_dir, env.settings.fernet_key))


def test_each_step_sends_the_case_file_not_a_chat_history(env):
    cid = open_unknown_debit_case(env)
    backend = FakeBackend().queue("AgentStep", search("APS PAPERS"), search("AP/2610/140"), {"notes": "done",
                                                                                               "final": FINAL})
    out = run_case(env.conn, cid, deps(env, backend))
    assert out.final.outcome == "NEEDS_OWNER"
    contents = [r.contents for r in backend.requests]
    assert contents[0].startswith("## Goal\nFind out what the ₹47,200 debit")
    assert '"tool"' not in contents[1] and '"notes"' not in contents[1]  # no earlier reply is resent
    assert "step 1, source search_gmail(query='APS PAPERS', limit=10)" in contents[1]
    assert "message 09-invoice-ashirwad-new-bank.eml" in contents[2]  # step 2's finding, from the file


def test_unknown_tools_bad_args_and_repeated_calls_are_refused_and_noted(env):
    cid = open_unknown_debit_case(env)
    backend = FakeBackend().queue(
        "AgentStep",
        {"notes": "try", "tool": {"name": "mark_paid", "args": {"payable_id": 1}}},
        {"notes": "try", "tool": {"name": "get_ledger", "args": {"table": "event"}}},
        search("APS"), search("APS"),
        {"notes": "done", "final": FINAL},
    )
    run_case(env.conn, cid, deps(env, backend))
    notes = cases.load(env.conn, cid).state["notes"]
    assert any("refused unknown tool 'mark_paid'" in n for n in notes)
    assert any("refused get_ledger: ('table',)" in n for n in notes)
    assert any("refused search_gmail: the same call as the step before" in n for n in notes)


def test_a_medium_run_that_hits_6_steps_reruns_at_high_then_asks_the_owner(env):
    cid = open_unknown_debit_case(env)
    backend = FakeBackend().queue("AgentStep", *[search(f"query {i}") for i in range(12)])
    out = run_case(env.conn, cid, deps(env, backend))
    assert out.final is None and [r.thinking for r in backend.requests] == ["medium"] * 6 + ["high"] * 6
    case = cases.load(env.conn, cid)
    assert (case.status, case.escalation_rule, case.thinking) == ("ASK_OWNER", escalation.MAX_STEPS, "high")
    q = env.conn.execute("SELECT kind, body_text FROM owner_question WHERE case_id = ?", (cid,)).fetchone()
    assert q[0] == "agent_question" and q[1].startswith("The assistant could not settle this case")


def test_a_stake_above_the_escalation_amount_starts_at_high(env):
    cid = open_unknown_debit_case(env, stake_paise=10_000_000)  # ₹1,00,000 > ₹50,000
    backend = FakeBackend().queue("AgentStep", {"notes": "done", "final": FINAL})
    run_case(env.conn, cid, deps(env, backend))
    assert backend.requests[0].thinking == "high"
    assert cases.load(env.conn, cid).escalation_rule == escalation.STAKE


def test_two_failed_candidates_end_the_medium_run(env):
    cid = open_unknown_debit_case(env)
    bad = {"notes": "propose", "tool": {"name": "add_candidate", "args": {
        "record_type": "bank_alert", "message_id": "09-invoice-ashirwad-new-bank.eml", "fields": {}}}}
    bad2 = {"notes": "again", "tool": {"name": "add_candidate", "args": {
        "record_type": "invoice", "message_id": "09-invoice-ashirwad-new-bank.eml", "fields": {}}}}
    backend = FakeBackend().queue("AgentStep", search("AP/2610/140"), bad, bad2, {"notes": "done", "final": FINAL})
    run_case(env.conn, cid, deps(env, backend))
    assert [r.thinking for r in backend.requests] == ["medium"] * 3 + ["high"]
    case = cases.load(env.conn, cid)
    assert case.validation_failures == 0 and any("medium run ended (max_validation_failures)" in n
                                                 for n in case.state["notes"])


def test_a_run_stopped_at_step_3_resumes_from_the_saved_case_file(env):
    cid = open_unknown_debit_case(env)
    backend = FakeBackend().queue("AgentStep", search("APS"), search("AP/2610/140"), RuntimeError("worker died"))
    with pytest.raises(RuntimeError):
        run_case(env.conn, cid, deps(env, backend))
    saved = cases.load(env.conn, cid)
    assert saved.steps == 2 and saved.state["steps_total"] == 2
    again = FakeBackend().queue("AgentStep", {"notes": "done", "final": FINAL})
    run_case(env.conn, cid, deps(env, again))
    assert len(again.requests) == 1  # steps 1 and 2 are not repeated
    sent = again.requests[0].contents
    assert sent.count("step 1, source search_gmail") == 1 and sent.count("step 2, source search_gmail") == 1
    assert cases.load(env.conn, cid).steps == 3


def test_escalation_rules_are_plain_code():
    assert escalation.start_thinking(5_000_001, 5_000_000) == ("high", escalation.STAKE)
    assert escalation.start_thinking(5_000_000, 5_000_000) == ("medium", None)
    assert escalation.run_over(6, 0, max_steps=6, max_failures=2) == escalation.MAX_STEPS
    assert escalation.run_over(2, 2, max_steps=6, max_failures=2) == escalation.MAX_FAILURES
    assert escalation.run_over(5, 1, max_steps=6, max_failures=2) is None
    assert (escalation.after_run("medium"), escalation.after_run("high")) == ("rerun_high", "ask_owner")


def test_a_long_tool_result_is_cut_in_the_case_file_and_whole_in_the_trace(env):
    import json
    from pathlib import Path

    env.conn.executemany("INSERT INTO party (business_id, kind, name) VALUES (1, 'vendor', ?)",
                         [(f"Bulk Vendor {i}",) for i in range(60)])
    env.conn.commit()
    cid = open_unknown_debit_case(env)
    get = {"notes": "list", "tool": {"name": "get_ledger", "args": {"table": "party", "party": "Bulk Vendor"}}}
    run_case(env.conn, cid, deps(env, FakeBackend().queue("AgentStep", get, {"notes": "done", "final": FINAL})))
    md = cases.load(env.conn, cid).case_file_md
    assert "Bulk Vendor 19" in md and "Bulk Vendor 20" not in md and "(+31 more lines in the trace)" in md
    traced = [s for f in Path(env.settings.trace_dir).rglob("*.jsonl")
              for s in map(json.loads, f.read_text(encoding="utf-8").splitlines()) if s.get("tool") == "agent:get_ledger"]
    assert len(traced[0]["result"].splitlines()) == 51  # 50 rows and the truncation line


def test_the_prompt_names_each_tools_arguments_as_its_model_does():
    import re

    from app.agent.tools import TOOLS
    from app.ai.client import load_prompt

    prompt = load_prompt("exception_agent.v1")
    for name, spec in TOOLS.items():
        bullet = re.search(rf"^- {name} \{{.*?(?=^- |^\n)", prompt, re.M | re.S)  # this tool's bullet only
        assert bullet, name
        written = set(re.findall(r'"([a-z_]+)"[:,}]', bullet.group(0)))
        assert set(spec.args_model.model_fields) <= written, (name, set(spec.args_model.model_fields) - written)
