"""The exception agent's read-only tools (batch 6, CHG-008, S3): search_gmail
remembers what it found; get_ledger reads on a read-only connection, this
business only, at most 50 rows; run_planner writes nothing."""

import sqlite3
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.agent.tools import TOOLS, LedgerArgs, PlannerArgs, SearchArgs, get_ledger, read_only, run_planner, search_gmail
from tests.agent_helpers import open_unknown_debit_case, tool_context
from tests.web_helpers import add_second_business, table_counts
from tests.worker_helpers import deliver, make_mail_env


@pytest.fixture
def env(tmp_path):
    e = make_mail_env(tmp_path)
    e.clock.advance(timedelta(days=2, hours=3))  # Wed 14 Oct, 12:00
    yield e
    e.conn.close()


def test_search_gmail_returns_ids_and_remembers_them(env):
    deliver(env, "08-invoice-ashirwad-ap131.eml", "09-invoice-ashirwad-new-bank.eml", "01-debit-ashirwad-paper.eml")
    ctx = tool_context(env, open_unknown_debit_case(env))
    out = search_gmail(ctx, SearchArgs(query="ashirwad invoice"))
    assert "message 09-invoice-ashirwad-new-bank.eml" in out and "message 08-invoice-ashirwad-ap131.eml" in out
    assert set(ctx.case.state["seen_message_ids"]) == {"09-invoice-ashirwad-new-bank.eml",
                                                       "08-invoice-ashirwad-ap131.eml"}
    assert search_gmail(ctx, SearchArgs(query="no such words here")) == "no messages match"
    with pytest.raises(ValidationError):
        SearchArgs(query="x", limit=21)


def test_get_ledger_is_read_only_this_business_only_and_at_most_50_rows(env):
    add_second_business(env)
    env.conn.executemany("INSERT INTO party (business_id, kind, name) VALUES (?, 'vendor', ?)",
                         [(1, f"Bulk Vendor {i}") for i in range(51)] + [(2, "Bulk Vendor Other")])
    env.conn.commit()
    ctx = tool_context(env, open_unknown_debit_case(env))
    out = get_ledger(ctx, LedgerArgs(table="party", party="Bulk Vendor"))
    lines = out.splitlines()
    assert len(lines) == 51 and lines[-1] == "(truncated at 50 rows)" and "Other" not in out
    ro = read_only(env.settings.database_path)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.execute("UPDATE payable SET status = 'PAID'")
    ro.close()


def test_get_ledger_reads_amounts_as_written_and_refuses_extra_args(env):
    ctx = tool_context(env, open_unknown_debit_case(env))
    out = get_ledger(ctx, LedgerArgs(table="payable", amount_text="Rs.1,80,000"))
    assert "amount_paise ₹1,80,000" in out and "PAPER-001" in out and len(out.splitlines()) == 1
    assert get_ledger(ctx, LedgerArgs(table="payable", amount_text="lots")).startswith("refused")
    with pytest.raises(ValidationError):
        LedgerArgs.model_validate({"table": "payable", "sql": "DELETE FROM payable"})
    with pytest.raises(ValidationError):
        LedgerArgs.model_validate({"table": "event"})


def test_run_planner_is_a_what_if_that_writes_nothing(env):
    ctx = tool_context(env, open_unknown_debit_case(env))
    before = table_counts(env)
    out = run_planner(ctx, PlannerArgs(drop_payable_ids=[5]))
    assert out.startswith("lowest balance ₹") and "bill 5" not in out
    assert table_counts(env) == before
    assert run_planner(ctx, PlannerArgs(receivable_dates={999: "2026-10-15"})).startswith("refused")


def test_the_read_tools_are_annotated_read_only():
    for name in ("search_gmail", "get_ledger", "run_planner"):
        assert "read_only" in TOOLS[name].annotations


# --- S4: add_candidate and ask_owner ----------------------------------------------------

from app.agent.tools import AskArgs, CandidateArgs, add_candidate, ask_owner  # noqa: E402
from app.ingest.store import DocumentStore  # noqa: E402
from tests.fake_ai import FIXTURE_REPLIES  # noqa: E402

BILL_09 = dict(FIXTURE_REPLIES["09-invoice-ashirwad-new-bank.eml"])["InvoiceExtract"]


def _ctx_after_search(env):
    deliver(env, "09-invoice-ashirwad-new-bank.eml")
    ctx = tool_context(env, open_unknown_debit_case(env))
    ctx.store = DocumentStore(env.settings.data_dir, env.settings.fernet_key)
    search_gmail(ctx, SearchArgs(query="AP/2610/140"))
    return ctx


def test_the_five_tools_and_nothing_else():
    assert set(TOOLS) == {"search_gmail", "get_ledger", "run_planner", "add_candidate", "ask_owner"}


def test_add_candidate_refuses_a_message_this_case_did_not_find(env):
    ctx = tool_context(env, open_unknown_debit_case(env))
    out = add_candidate(ctx, CandidateArgs(record_type="invoice", message_id="09-invoice-ashirwad-new-bank.eml",
                                           fields=BILL_09))
    assert out == "refused: message 09-invoice-ashirwad-new-bank.eml did not come from this case's searches"
    assert env.conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 0


def test_add_candidate_runs_the_pipelines_checks_and_never_writes_the_ledger(env):
    ctx = _ctx_after_search(env)
    before = table_counts(env)
    out = add_candidate(ctx, CandidateArgs(record_type="invoice", message_id="09-invoice-ashirwad-new-bank.eml",
                                           fields=BILL_09))
    assert out.endswith("VALID, every rule check passed")
    row = env.conn.execute("SELECT record_type, status, created_by, payload_json FROM candidate").fetchone()
    assert tuple(row[:3]) == ("payable", "VALID", f"agent:case:{ctx.case.id}")
    import json
    assert json.loads(row[3])["found_by"] == f"agent:case:{ctx.case.id} via gmail:09-invoice-ashirwad-new-bank.eml"
    after = table_counts(env)
    assert all(after[t] == before[t] for t in ("payable", "receivable", "bank_txn", "event"))
    assert ctx.case.validation_failures == 0


def test_a_candidate_that_fails_its_checks_counts_against_the_case(env):
    ctx = _ctx_after_search(env)
    out = add_candidate(ctx, CandidateArgs(record_type="invoice", message_id="09-invoice-ashirwad-new-bank.eml",
                                           fields={**BILL_09, "total_text": "Rs.50,000.00"}))
    assert out.startswith("candidate ") and "INVALID (invoice_arithmetic:" in out
    out = add_candidate(ctx, CandidateArgs(record_type="bank_alert", message_id="09-invoice-ashirwad-new-bank.eml",
                                           fields={"amount_text": "Rs.47,200"}))
    assert "INVALID" in out and ctx.case.validation_failures == 2


def test_ask_owner_limits_one_open_question_and_ends_the_run(env):
    ctx = tool_context(env, open_unknown_debit_case(env))
    with pytest.raises(ValidationError):
        AskArgs(question="x" * 301)
    with pytest.raises(ValidationError):
        AskArgs(question="Which?", choices=["a", "b", "c", "d", "e"])
    with pytest.raises(ValidationError):  # the owner answers by choosing: a question needs a choice
        AskArgs(question="Which?")
    assert ask_owner(ctx, AskArgs(question="Which?", choices=["y" * 61])).startswith("refused")
    out = ask_owner(ctx, AskArgs(question="Was the ₹47,200 to APS PAPERS for Ashirwad's paper?",
                                 choices=["Yes", "No"]))
    assert out.startswith("question ") and ctx.case.status == "ASK_OWNER"
    assert ask_owner(ctx, AskArgs(question="Again?", choices=["Yes"])).startswith("refused: question")
    q = env.conn.execute("SELECT kind, case_id, choices_json FROM owner_question WHERE kind = 'agent_question'"
                         ).fetchone()
    assert (q[0], q[1]) == ("agent_question", ctx.case.id) and '"choices": ["Yes", "No"]' in q[2]
    assert TOOLS["ask_owner"].annotations == frozenset({"asks_owner", "ends_run"})


def test_ask_owner_asks_once_a_resumed_case_must_answer(env):
    ctx = tool_context(env, open_unknown_debit_case(env))
    ctx.case.state["resumed"] = True
    assert ask_owner(ctx, AskArgs(question="Again?", choices=["Yes"])) == (
        "refused: the owner has answered this case once; give a final answer")
    assert ctx.case.status == "OPEN"
