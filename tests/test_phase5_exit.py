"""TDD Phase 5 exit (batch 3 plan, CHG-006 S6; AC1, AC9): the owner plays
through Part 1's worked example in the app, through the real routes on the
seeded database, with the real worker and the fake AI reading the test inbox.

- Mon 12 Oct: the plan shows ₹1,83,000 on Thu 22, ₹67,000 below. The owner
  types and confirms a bill, approves Monday, asks Nandi Foods to pay early,
  and marks Paper paid.
- Thu 15 Oct: Paper's debit and Kaveri's credit arrive; the owner approves Thursday.
- Fri 16 Oct: Nandi's ₹2,00,000 arrives, is matched and CONFIRMED, and the
  plan reruns: Prime Chem PAY on Thu 22, lowest ₹3,83,000 (Part 1, "What
  happens next").

A helper logged in alongside sees only /add at every step. Every owner
action leaves an event with actor owner:1 (PO addition to AC1).
"""

import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.clock import TIMEZONE
from app.jobs import queue
from app.worker import default_handlers
from tests.fake_ai import fixture_backend
from tests.web_helpers import (
    HELPER,
    approve_form,
    current_run,
    day_row,
    last_event_id,
    login,
    make_web_env,
    page_text,
    plan_lines,
    plan_now,
    post,
    statuses,
    version,
)
from tests.worker_helpers import deliver, run_all

PAPER, PFESI, ELEC, GST, PRIME = 1, 2, 3, 4, 5
KAVERI, NANDI = 1, 2
OWNER_PAGES = ("/", "/attention", "/accounts", "/settings", "/api/plan/current")


@pytest.fixture
def web(tmp_path):
    env, owner = make_web_env(tmp_path)  # Mon 12 Oct 2026, 09:00
    helper = TestClient(owner.app)
    yield env, owner, helper
    env.conn.close()


def at(env, day, hour):
    env.clock.advance(datetime(2026, 10, day, hour, tzinfo=TIMEZONE) - env.clock.now())


def mail(env, handlers, *names):
    deliver(env, *names)
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    run_all(env, handlers)


def helper_sees_only_add(helper):
    assert helper.get("/add").status_code == 200
    for path in OWNER_PAGES:
        assert helper.get(path, follow_redirects=False).status_code == 403


def lowest(page):
    return re.search(r"<strong[^>]*>(₹[0-9,]+)</strong>\s*on ([A-Za-z]+ \d+ [A-Za-z]+)", page).groups()


def test_the_owner_plays_through_the_worked_example(web):
    env, owner, helper = web
    handlers = default_handlers(fixture_backend("01-debit-ashirwad-paper.eml", "02-credit-kaveri-traders.eml",
                                                "07-credit-nandi-foods.eml"))
    plan_now(env)  # the Monday plan, as the worker's monday_plan job makes it at 07:00
    start = last_event_id(env)
    actions = []  # (what the owner did, the events it must leave)

    # --- Mon 12 Oct, 09:00 ------------------------------------------------------------
    csrf = login(owner)
    login(helper, HELPER)
    helper_sees_only_add(helper)
    page = owner.get("/").text
    assert lowest(page) == ("₹1,83,000", "Thu 22 Oct")
    assert "₹67,000 below" in page

    # The owner types a bill (due after the horizon) and confirms it.
    bill = {"kind": "bill", "party": "Sharma Packaging", "invoice_number": "SP-7", "amount": "12,000",
            "due_date": "2026-11-05", "priority": "normal"}
    assert post(owner, "/entries", csrf, bill).status_code == 303
    (cid,) = dict.fromkeys(re.findall(r"/candidates/(\d+)/confirm", owner.get("/attention").text))
    before = current_run(env)["id"]
    assert post(owner, f"/candidates/{cid}/confirm", csrf, bill).status_code == 303
    actions.append(("confirm a typed bill", {"PAYABLE_CREATED", "PAYABLE_CONFIRMED", "CANDIDATE_ACCEPTED"}))
    sharma = env.conn.execute("SELECT id FROM payable WHERE invoice_number = 'SP-7'").fetchone()[0]
    assert current_run(env)["id"] != before  # the plan updated
    assert plan_lines(env)[sharma][0] == "WAIT"
    assert "Sharma Packaging ₹12,000" in page_text(owner.get("/").text)
    helper_sees_only_add(helper)

    # The owner approves Monday: only Paper.
    run_id, versions = approve_form(owner.get("/").text)
    assert post(owner, f"/plans/{run_id}/approve", csrf, versions).status_code == 303
    actions.append(("approve Monday", {"PAYABLE_PAYMENT_EXPECTED"}))
    assert statuses(env)[PAPER] == "PAYMENT_EXPECTED"

    # The owner chooses to ask Nandi Foods to pay early.
    attention = owner.get("/attention").text
    label = "Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct"
    option_id = re.search(re.escape(label) + r".*?/options/(\d+)/choose", attention, re.S).group(1)
    assert post(owner, f"/options/{option_id}/choose", csrf).status_code == 303
    actions.append(("choose the Nandi option", {"SHORTFALL_OPTION_CHOSEN"}))

    # The owner pays Paper in the bank app and marks it paid; the plan still counts it.
    assert post(owner, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))}).status_code == 303
    actions.append(("mark Paper paid", {"PAYABLE_PAID"}))
    assert lowest(owner.get("/").text) == ("₹1,83,000", "Thu 22 Oct")
    helper_sees_only_add(helper)

    # --- Thu 15 Oct, 09:00 --------------------------------------------------------------
    at(env, 15, 9)
    mail(env, handlers, "01-debit-ashirwad-paper.eml", "02-credit-kaveri-traders.eml")
    paper = env.conn.execute("SELECT status, matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert paper["status"] == "PAID" and paper["matched_txn_id"] is not None  # linked, not an unknown debit
    assert env.conn.execute("SELECT confidence FROM receivable WHERE id = ?", (KAVERI,)).fetchone()[0] == "CONFIRMED"
    assert env.conn.execute("SELECT COUNT(*) FROM agent_case").fetchone()[0] == 0
    page = owner.get("/").text
    assert "Approve Thu 15 Oct" in page
    run_id, versions = approve_form(page)
    assert set(versions) == {f"version_{PFESI}", f"version_{ELEC}"}
    assert post(owner, f"/plans/{run_id}/approve", csrf, versions).status_code == 303
    actions.append(("approve Thursday", {"PAYABLE_PAYMENT_EXPECTED"}))
    helper_sees_only_add(helper)

    # --- Fri 16 Oct, 11:00 --------------------------------------------------------------
    at(env, 16, 11)
    mail(env, handlers, "07-credit-nandi-foods.eml")
    assert env.conn.execute("SELECT confidence FROM receivable WHERE id = ?", (NANDI,)).fetchone()[0] == "CONFIRMED"
    run = current_run(env)
    assert run["triggered_by"].startswith("event:") and run["created_at"].startswith("2026-10-16")
    assert (run["opening_cash_paise"], run["lowest_balance_paise"], run["lowest_on"]) == (
        67_300_000, 38_300_000, "2026-10-22")
    assert plan_lines(env)[PRIME] == ("PAY", "2026-10-22")
    assert plan_lines(env)[GST] == ("PAY", "2026-10-19")
    page = owner.get("/").text
    assert lowest(page) == ("₹3,83,000", "Thu 22 Oct")
    thursday = day_row(page, "2026-10-22")
    assert "Prime Chem Industries ₹1,20,000" in thursday and "₹3,83,000" in thursday
    helper_sees_only_add(helper)

    # --- the audit trail ---------------------------------------------------------------
    owner_rows = env.conn.execute(
        "SELECT event_type, actor FROM event WHERE id > ? AND actor LIKE 'owner:%' ORDER BY id", (start,)
    ).fetchall()
    assert {r["actor"] for r in owner_rows} == {"owner:1"}
    recorded = [r["event_type"] for r in owner_rows]
    for what, needed in actions:
        for event_type in needed:
            assert event_type in recorded, f"{what}: no {event_type} event"
            recorded.remove(event_type)
    assert recorded == ["PAYABLE_PAYMENT_EXPECTED"]  # Thursday approved two bills: one event each
    by_system = {r[0] for r in env.conn.execute("SELECT DISTINCT actor FROM event WHERE id > ?", (start,))}
    assert by_system == {"owner:1", "planner", "pipeline", "reconciler"}  # never an agent
