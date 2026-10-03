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
