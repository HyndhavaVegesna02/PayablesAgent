"""The scripted owner holds up when a live model leaves the canned path
(CHG-043). Live workflow B read a statement's ₹590 row with no counterparty,
and its agent offered choices of its own: the owner now finds a debit's
question by amount (and date), and presses the one offered choice that a
step's stated rule names, or fails the step saying what was offered."""

import sqlite3

import pytest

from evals.workflow import StepFailed
from evals.workflow_runs import answer_by_choice, debit_question
from tests.test_workflow import _browser, _Client, _Page


class _Run:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE bank_txn (id INTEGER PRIMARY KEY, direction TEXT, amount_paise INTEGER, txn_date TEXT,
                                   counterparty TEXT);
            CREATE TABLE agent_case (id INTEGER PRIMARY KEY, subject_ref TEXT);
            CREATE TABLE owner_question (id INTEGER PRIMARY KEY, case_id INTEGER, kind TEXT, choices_json TEXT,
                                         status TEXT);
            INSERT INTO bank_txn VALUES (1, 'debit', 59000, '2026-10-13', NULL),
                                        (2, 'debit', 1250000, '2026-10-14', 'RAMESH K'),
                                        (3, 'debit', 1500000, '2026-10-14', 'ASHIRWAD PAPER'),
                                        (4, 'debit', 1500000, '2026-10-15', 'ASHIRWAD PAPER');
            INSERT INTO agent_case VALUES (7, 'bank_txn:2');
            INSERT INTO owner_question VALUES (10, NULL, 'explain_txn', '{"bank_txn_id": 1}', 'OPEN'),
                                              (11, 7, 'agent_question', '{"case_id": 7, "choices": []}', 'OPEN'),
                                              (12, NULL, 'explain_txn', '{"bank_txn_id": 3}', 'OPEN'),
                                              (13, NULL, 'explain_txn', '{"bank_txn_id": 4}', 'OPEN');
        """)

    def rows(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()


def test_a_debit_question_is_found_by_amount_even_with_no_counterparty():
    run = _Run()
    assert debit_question(run, "explain_txn", 59000) == 10  # the live statement row: counterparty NULL
    assert debit_question(run, "agent_question", 1250000) == 11  # through its case's subject
    assert debit_question(run, "explain_txn", 1500000, on="2026-10-15") == 13  # the date tells two apart


def test_two_matches_fail_the_step_rather_than_pick_one():
    with pytest.raises(StepFailed, match="2 open explain_txn questions about a debit of 1500000 paise"):
        debit_question(_Run(), "explain_txn", 1500000)


CHOICES = """<form action="/questions/11/answer" method="post"><input type="hidden" name="csrf_token" value="t">
<button type="submit" name="choice" value="Salary/Wage">Salary/Wage</button>
<button type="submit" name="choice" value="Advance to staff">Advance to staff</button></form>"""


def _owner(html):
    b = _browser()

    class Client(_Client):
        def get(self, path):
            return _Page(html)

    b.client = Client()
    return b


def test_the_owner_presses_the_one_choice_the_rule_names():
    run = type("R", (), {})()
    run.owner = _owner(CHOICES)
    assert answer_by_choice(run, 11, "advance") == "Advance to staff"
    ((path, data),) = run.owner.client.posted
    assert path == "/questions/11/answer" and data["choice"] == "Advance to staff"


def test_no_matching_choice_fails_the_step_and_lists_what_was_offered():
    run = type("R", (), {})()
    run.owner = _owner(CHOICES.replace("Advance to staff", "Loan"))
    with pytest.raises(StepFailed, match=r"choice not offered: wanted exactly one containing 'advance'; "
                                         r"offered \['Salary/Wage', 'Loan'\]"):
        answer_by_choice(run, 11, "advance")
    assert run.owner.client.posted == []  # never guesses


def test_a_bill_with_no_number_is_found_by_amount_and_due_date_not_the_vendor_name_read():
    """CHG-045: live, workflow A's voice bill was planned under a vendor name read differently from
    'Sharma Packaging', and the check keyed by name missed it."""
    from evals.workflow_runs import decision_by_amount

    run = _Run()
    run.conn.executescript("""
        CREATE TABLE plan_run (id INTEGER PRIMARY KEY, is_current INTEGER);
        CREATE TABLE payable (id INTEGER PRIMARY KEY, invoice_number TEXT, amount_paise INTEGER, due_date TEXT);
        CREATE TABLE plan_line (plan_run_id INTEGER, payable_id INTEGER, decision TEXT, pay_on TEXT);
        INSERT INTO plan_run VALUES (1, 0), (2, 1);
        INSERT INTO payable VALUES (6, NULL, 15000000, '2026-11-05'), (7, 'LT/2610/88', 1800000, '2026-11-02');
        INSERT INTO plan_line VALUES (1, 6, 'PAY', '2026-10-15'), (2, 6, 'WAIT', NULL), (2, 7, 'WAIT', NULL);
    """)
    run.one = lambda sql, args=(): (run.conn.execute(sql, args).fetchone() or [None])[0]
    assert decision_by_amount(run, 15000000, "2026-11-05") == "WAIT"  # the current plan's line
    assert decision_by_amount(run, 15000000, "2026-11-06") is None
