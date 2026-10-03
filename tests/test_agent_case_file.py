"""The case file (batch 6, CHG-008, S1): five parts rendered by code from the
case state; a tool result is cut to 20 lines in the file."""

from app.agent.case_file import MAX_RESULT_LINES, finding, parse_opening, render
from app.ledger.reconcile import case_file


def test_the_reconcilers_opening_file_is_parsed_into_its_parts():
    md = case_file("Explain the debit", ["Debit ₹47,200 on Wed 14 Oct", "Payee: APS PAPERS"], ["Which bill?"])
    state = parse_opening(md)
    assert state == {"goal": "Explain the debit", "facts": ["Debit ₹47,200 on Wed 14 Oct", "Payee: APS PAPERS"],
                     "unknowns": ["Which bill?"], "findings": [], "notes": []}


def test_the_file_has_the_five_parts_in_order():
    md = render(parse_opening(case_file("g", ["f"], ["u"])))
    heads = [line for line in md.splitlines() if line.startswith("## ")]
    assert heads == ["## Goal", "## Facts", "## Findings", "## Unknowns", "## Notes"]


def test_a_long_result_is_cut_to_20_lines_with_a_pointer_to_the_trace():
    result = "\n".join(f"line {i}" for i in range(60))
    state = {**parse_opening(case_file("g", [], [])), "findings": [finding(1, "search_gmail", "query='x'", result)]}
    md = render(state)
    assert "line 19" in md and "line 20" not in md
    assert "(+40 more lines in the trace)" in md and MAX_RESULT_LINES == 20
    assert "step 1, source search_gmail(query='x')" in md


def test_migration_0003_adds_case_state_and_the_agent_question(tmp_path):
    import sqlite3

    import pytest

    from tests.worker_helpers import make_env

    env = make_env(tmp_path)
    env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, status) "
                     "VALUES (1, 'agent_question', 'Was this debit rent?', 'OPEN')")
    with pytest.raises(sqlite3.IntegrityError):
        env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, status) "
                         "VALUES (1, 'something_else', 'x', 'OPEN')")
    cols = {r[1]: r[4] for r in env.conn.execute("PRAGMA table_info(agent_case)")}
    assert cols["state_json"] == "'{}'"
    env.conn.close()
