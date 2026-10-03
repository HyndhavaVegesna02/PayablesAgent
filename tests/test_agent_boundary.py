"""The agent's write boundary (batch 6, CHG-008; the PO's brief): it never
imports app.ledger.writer (import-linter), and its only SQL writes are the
narrow inserts into candidate and owner_question, the update of its own
agent_case row (Q2), and, for a message the mail poll never stored, the
insert of that message as a source document (add_candidate; not ledger
state). This scan holds the second half."""

import ast
import re
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent / "app" / "agent"
# SQL shapes only (prose that says "update" is not a write): INSERT INTO t,
# REPLACE INTO t, UPDATE t SET, DELETE FROM t.
WRITE = re.compile(
    r"\b(?:(?:INSERT(?:\s+OR\s+\w+)?|REPLACE)\s+INTO\s+(\w+)|UPDATE(?:\s+OR\s+\w+)?\s+(\w+)\s+SET\b"
    r"|DELETE\s+FROM\s+(\w+))",
    re.IGNORECASE,
)
ALLOWED = {"candidate", "owner_question", "agent_case", "source_document"}


def sql_writes(source: str) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [(node.lineno, next(g for g in m.groups() if g).lower()) for m in WRITE.finditer(node.value)]
    return found


def test_the_agent_writes_only_candidate_owner_question_and_its_own_case():
    bad = [f"{p.name}:{line} writes {table}" for p in sorted(AGENT.glob("*.py"))
           for line, table in sql_writes(p.read_text(encoding="utf-8")) if table not in ALLOWED]
    assert bad == []


def test_the_scan_sees_a_write_and_not_prose():
    assert sql_writes('x = "UPDATE payable SET status = 1"') == [(1, "payable")]
    assert sql_writes('x = "INSERT INTO bank_txn (a) VALUES (1)"') == [(1, "bank_txn")]
    assert sql_writes('"""Its own UPDATE of the row."""') == []


def test_the_agent_package_exists_with_a_case_store():
    assert (AGENT / "cases.py").exists() and (AGENT / "case_file.py").exists()
