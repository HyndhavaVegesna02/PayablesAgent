"""This week, approve and mark paid (batch 3 plan, CHG-006 S2 and S4; AC3),
through the real routes on the seeded worked example at Mon 12 Oct 09:00."""

from datetime import timedelta

import pytest

from app.ledger import writer
from app.ledger.writer import EntityRef
from tests.web_helpers import (
    approve_form,
    current_run,
    day_row,
    login,
    make_web_env,
    owner_events,
    page_text,
    last_event_id,
    plan_now,
    post,
    statuses,
    version,
)

PAPER, PFESI, ELEC, GST, PRIME = 1, 2, 3, 4, 5
STALE = "The plan changed since you opened it. Here is the current plan."


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def test_this_week_shows_the_worked_example_figures(web):
    _, client, _ = web
    page = client.get("/").text
    text = page_text(page)
    assert "Lowest balance ₹1,83,000 on Thu 22 Oct" in text
    assert "₹67,000 below your safety amount on Thu 22 Oct" in text and "Safety amount ₹2,50,000" in text
    assert "Approve Mon 12 Oct" in page
    assert "Ashirwad Paper Suppliers ₹1,80,000" in day_row(page, "2026-10-12")  # under Mon 12
    assert "Prime Chem Industries ₹1,20,000 Needs your decision" in text
    for day, iso, balance in (("Mon 12 Oct", "2026-10-12", "₹4,40,000"), ("Thu 15 Oct", "2026-10-15", "₹3,93,000"),
                              ("Mon 19 Oct", "2026-10-19", "₹3,03,000"), ("Thu 22 Oct", "2026-10-22", "₹1,83,000")):
        row = day_row(page, iso)
        assert row.startswith(day) and balance in row


def test_money_in_the_plan_counted_shows_on_its_day_and_the_balance_is_the_plans(web):
    env, client, _ = web
    page = client.get("/").text
    tuesday = day_row(page, "2026-10-13")
    # The row still reads day, payments, balance first; Kaveri's committed ₹33,000 follows as money in.
    assert tuesday.startswith("Tue 13 Oct ₹4,73,000")
    assert "+₹33,000 Kaveri Traders · in Expected in" in tuesday
    balances = dict(env.conn.execute("SELECT day, balance_paise FROM plan_day WHERE plan_run_id = ?",
                                     (current_run(env)["id"],)).fetchall())
    assert balances["2026-10-13"] - balances["2026-10-12"] == 3_300_000  # what the row shows coming in
    assert "· in" not in day_row(page, "2026-10-12")


def test_no_plan_yet_offers_no_approval(tmp_path):
    env, client = make_web_env(tmp_path)
    login(client)
    page = client.get("/").text
    assert "No plan yet" in page and "/approve" not in page
    env.conn.close()


def test_approve_moves_only_the_monday_pay_line_and_replans(web):
    env, client, csrf = web
    run_id, versions = approve_form(client.get("/").text)
    assert set(versions) == {f"version_{PAPER}"}
    mark = last_event_id(env)
    r = post(client, f"/plans/{run_id}/approve", csrf, versions)
    assert (r.status_code, r.headers["location"]) == (303, "/")
    assert statuses(env) == {PAPER: "PAYMENT_EXPECTED", PFESI: "PLANNED", ELEC: "PLANNED", GST: "PLANNED",
                             PRIME: "CONFIRMED"}
    assert owner_events(env, mark) == [("PAYABLE_PAYMENT_EXPECTED", "owner:1")]
    approved = env.conn.execute("SELECT approved_by FROM payable WHERE id = ?", (PAPER,)).fetchone()[0]
    assert approved == 1
    new_run = current_run(env)
    assert new_run["id"] != run_id and new_run["triggered_by"] == f"event:{mark + 1}"
    page = client.get("/").text
    assert "Approve Thu 15 Oct" in page and "Approved, waiting to be paid" in page


def test_approving_twice_is_refused_as_stale(web):
    env, client, csrf = web
    run_id, versions = approve_form(client.get("/").text)
    post(client, f"/plans/{run_id}/approve", csrf, versions)
    before = statuses(env)
    r = post(client, f"/plans/{run_id}/approve", csrf, versions)
    assert r.status_code == 409 and STALE in r.text
    assert "Approve Thu 15 Oct" in r.text  # the current figures, re-rendered
    assert statuses(env) == before


def test_a_run_that_is_no_longer_current_is_refused(web):
    env, client, csrf = web
    run_id, versions = approve_form(client.get("/").text)
    plan_now(env, "event:99")  # another replan made a new current run
    r = post(client, f"/plans/{run_id}/approve", csrf, versions)
    assert r.status_code == 409 and STALE in r.text
    assert statuses(env)[PAPER] == "PLANNED"


def test_a_changed_input_is_refused_even_when_the_run_is_still_current(web):
    env, client, csrf = web
    run_id, versions = approve_form(client.get("/").text)
    # A bill changes without a replan (as a write from the worker could, between replans).
    writer.split_payable(EntityRef("payable", PRIME), 5_000_000, env.clock.today() + timedelta(days=20),
                         "owner:1", "split", None, conn=env.conn, expected_version=version(env, PRIME),
                         clock=env.clock)
    assert current_run(env)["id"] == run_id
    r = post(client, f"/plans/{run_id}/approve", csrf, versions)
    assert r.status_code == 409 and STALE in r.text
    assert statuses(env)[PAPER] == "PLANNED"


def test_the_next_day_makes_yesterdays_plan_stale(web):
    env, client, csrf = web
    run_id, versions = approve_form(client.get("/").text)
    env.clock.advance(timedelta(days=1))
    r = post(client, f"/plans/{run_id}/approve", csrf, versions)
    assert r.status_code == 409 and STALE in r.text
    assert statuses(env)[PAPER] == "PLANNED"


@pytest.mark.parametrize("versions", [{}, {f"version_{PAPER}": "1"}, {f"version_{PAPER}": "x"}])
def test_a_bill_version_that_is_not_the_one_on_the_page_is_refused(web, versions):
    env, client, csrf = web
    run_id, _ = approve_form(client.get("/").text)
    r = post(client, f"/plans/{run_id}/approve", csrf, versions)
    assert r.status_code == 409 and STALE in r.text
    assert statuses(env)[PAPER] == "PLANNED"


def _approve_monday(env, client, csrf):
    run_id, versions = approve_form(client.get("/").text)
    post(client, f"/plans/{run_id}/approve", csrf, versions)


def test_mark_paid_moves_an_approved_bill_to_paid_and_keeps_it_in_the_plan(web):
    env, client, csrf = web
    _approve_monday(env, client, csrf)
    mark = last_event_id(env)
    r = post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))})
    assert r.status_code == 303
    assert statuses(env)[PAPER] == "PAID"
    assert owner_events(env, mark) == [("PAYABLE_PAID", "owner:1")]
    # D12: no debit has arrived, so the plan still subtracts the payment.
    run = current_run(env)
    assert (run["lowest_balance_paise"], run["lowest_on"]) == (18_300_000, "2026-10-22")


def test_mark_paid_on_a_review_bill_links_the_debit_it_was_held_for(web):
    env, client, csrf = web
    _approve_monday(env, client, csrf)
    from tests.reconcile_helpers import txn

    t = txn(env, "debit", 18_000_000, env.clock.today(), "SOMEONE ELSE")  # amount and date fit, name does not
    from app.ledger.reconcile import match_debit

    with writer.atomic(env.conn):  # as the reconcile_txn job runs it
        match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert statuses(env)[PAPER] == "REVIEW"
    plan_now(env, "event:review")
    r = post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))})
    assert r.status_code == 303
    row = env.conn.execute("SELECT status, matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert tuple(row) == ("PAID", t)
    run = current_run(env)  # the debit carries the outflow; it is not subtracted twice
    assert (run["lowest_balance_paise"], run["lowest_on"]) == (18_300_000, "2026-10-22")


def test_mark_paid_is_refused_for_a_planned_bill(web):
    env, client, csrf = web
    r = post(client, f"/payables/{PFESI}/mark-paid", csrf, {"version": str(version(env, PFESI))})
    assert r.status_code == 409 and "only an approved payment can be marked paid" in r.text
    assert statuses(env)[PFESI] == "PLANNED"


def test_mark_paid_with_an_old_version_is_refused(web):
    env, client, csrf = web
    _approve_monday(env, client, csrf)
    r = post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": "1"})
    assert r.status_code == 409 and "changed since you opened the page" in r.text
    assert statuses(env)[PAPER] == "PAYMENT_EXPECTED"


def test_an_unknown_bill_is_404(web):
    _, client, csrf = web
    assert post(client, "/payables/999/mark-paid", csrf, {"version": "1"}).status_code == 404


def test_an_htmx_action_redirects_through_hx_redirect(web):
    env, client, csrf = web
    run_id, versions = approve_form(client.get("/").text)
    r = post(client, f"/plans/{run_id}/approve", csrf, versions, headers={"HX-Request": "true"})
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/"


def test_an_htmx_page_request_gets_only_the_main_block(web):
    _, client, _ = web
    r = client.get("/", headers={"HX-Request": "true"})
    assert "<html" not in r.text and "<h1>This week</h1>" in r.text
