"""Batch 3 review round 1 fixes (docs/batches/2026-10-03-3/review.md). Each test
names the finding it pins."""

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import demo
from app.clock import DEMO_CLOCK_FILE, TIMEZONE, DemoClock, clock_for
from app.db.read import build_snapshot
from app.domain.states import ActorNotAllowed, IllegalTransition
from app.ledger import writer
from app.ledger.reconcile import handle_failure, match_debit
from app.ledger.writer import EntityRef
from app.main import create_app
from tests.reconcile_helpers import PAPER, cases, plan_and_approve, status, txn
from tests.test_reconcile_failure import REF, notice
from tests.web_helpers import (
    add_second_business,
    approve_form,
    current_run,
    login,
    make_web_env,
    plan_now,
    post,
    statuses,
    version,
)
from tests.worker_helpers import make_env

OCT = lambda d: date(2026, 10, d)  # noqa: E731


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _owner_paid(env, bill_id):
    writer.transition(EntityRef("payable", bill_id), "PAID", "owner:1", "owner marked paid", None,
                      conn=env.conn, expected_version=version(env, bill_id), clock=env.clock)


# --- reviewer A, critical 1: approval after a date rollover ------------------------------


def test_after_a_quiet_day_change_the_refusal_page_carries_a_plan_that_can_be_approved(web):
    env, client, csrf = web
    old_run, versions = approve_form(client.get("/").text)
    env.clock.advance(timedelta(days=3))  # Thu 15, no mail, no replan
    r = post(client, f"/plans/{old_run}/approve", csrf, versions)
    assert r.status_code == 409 and "The plan changed since you opened it" in r.text
    new_run, new_versions = approve_form(r.text)
    assert new_run != old_run and current_run(env)["id"] == new_run
    assert current_run(env)["created_at"].startswith("2026-10-15")
    assert post(client, f"/plans/{new_run}/approve", csrf, new_versions).status_code == 303


def test_a_stale_option_choice_also_refreshes_the_plan(web):
    env, client, csrf = web
    option_id = env.conn.execute("SELECT id FROM shortfall_option WHERE kind = 'early_receipt'").fetchone()[0]
    env.clock.advance(timedelta(days=1))
    r = post(client, f"/options/{option_id}/choose", csrf)
    assert r.status_code == 409
    assert env.conn.execute("SELECT chosen_by FROM shortfall_option WHERE id = ?", (option_id,)).fetchone()[0] is None
    assert current_run(env)["created_at"].startswith("2026-10-13")


# --- reviewer A, majors ------------------------------------------------------------------


def test_a_non_ascii_csrf_token_is_403_not_500(web):
    env, client, csrf = web
    assert post(client, "/plans/1/approve", "é").status_code == 403
    fresh = TestClient(client.app)
    fresh.get("/login")
    r = fresh.post("/login", data={"email": "owner@example.test", "password": "owner-demo-pass", "csrf_token": "é"},
                   follow_redirects=False)
    assert r.status_code == 403


def test_confirming_an_alert_with_amount_zero_is_a_field_error(web):
    env, client, csrf = web
    from tests.test_web_attention import _awaiting_alert

    cid, _ = _awaiting_alert(env)
    r = post(client, f"/candidates/{cid}/confirm", csrf,
             {"account_id": "1", "direction": "debit", "amount": "0", "txn_date": "2026-10-12"})
    assert r.status_code == 422 and "above zero" in r.text


def test_an_unknown_path_is_the_plain_not_found_page(web):
    _, client, _ = web
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "<html" in r.text and "detail" not in r.text


def test_question_choices_that_are_not_an_object_are_refused(web):
    env, client, csrf = web
    qid = env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, choices_json, status) "
                           "VALUES (1, 'confirm_record', 'x', '[1]', 'OPEN')").lastrowid
    env.conn.commit()
    assert post(client, f"/questions/{qid}/answer", csrf).status_code == 409


def test_confirm_balance_answers_only_the_question_about_that_account(web):
    env, client, csrf = web
    writer.record_reported_balance(1, 41_200_000, "2026-10-12T08:30:00+05:30", "reconciler", "r", None,
                                   conn=env.conn, reconciled=False, clock=env.clock)
    writer.set_drift_status(1, "CHECKING", "reconciler", "gap", None, conn=env.conn, clock=env.clock)
    writer.set_drift_status(1, "ASK_OWNER", "reconciler", "gap", None, conn=env.conn, clock=env.clock)
    for account_id in (1, 7):
        env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, choices_json, status) "
                         "VALUES (1, 'confirm_balance', 'x', ?, 'OPEN')", (json.dumps({"account_id": account_id}),))
    env.conn.commit()
    post(client, "/accounts/1/confirm-balance", csrf, {"amount": "4,12,000"})
    rows = env.conn.execute("SELECT json_extract(choices_json, '$.account_id'), status FROM owner_question "
                            "ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1, "ANSWERED"), (7, "OPEN")]


def test_a_paid_bill_waiting_for_its_debit_shows_on_its_day(web):
    env, client, csrf = web
    run_id, versions = approve_form(client.get("/").text)
    post(client, f"/plans/{run_id}/approve", csrf, versions)
    post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))})
    row = client.get("/").text.split("<td>Mon 12 Oct</td>")[1].split("</tr>")[0]
    assert "Ashirwad Paper Suppliers ₹1,80,000" in row and "bank debit not linked yet" in row


def test_blank_seed_passwords_are_refused(tmp_path):
    from app.db.connection import write_connection
    from app.db.migrate import apply_migrations
    from fixtures.seed import seed

    db = tmp_path / "s.db"
    apply_migrations(db)
    conn = write_connection(db)
    with pytest.raises(ValueError, match="must not be blank"):
        seed(conn, owner_password=" ")
    conn.close()


# --- reviewer B, C1: REOPENED clears the old debit link -----------------------------------


def test_a_reopened_bill_loses_its_old_debit_link(env):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS", REF)
    match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert status(env, "payable", PAPER) == "PAID"
    handle_failure(env.conn, notice(env), window_days=3, clock=env.clock)
    row = env.conn.execute("SELECT status, matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert tuple(row) == ("REOPENED", None)
    ev = env.conn.execute("SELECT before_json FROM event WHERE event_type = 'PAYABLE_REOPENED'").fetchone()
    assert json.loads(ev[0])["matched_txn_id"] == t  # the old link stays in the audit trail


def test_a_retried_bill_marked_paid_still_counts_until_its_new_debit(env):
    from app.jobs.replan import replan

    plan_and_approve(env, PAPER)
    first = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS", REF)
    match_debit(env.conn, first, window_days=3, clock=env.clock)
    handle_failure(env.conn, notice(env), window_days=3, clock=env.clock)
    replan(env.conn, 1, triggered_by="t", clock=env.clock)
    writer.transition(EntityRef("payable", PAPER), "PAYMENT_EXPECTED", "owner:1", "re-approved", None,
                      conn=env.conn, expected_version=version(env, PAPER), clock=env.clock)
    _owner_paid(env, PAPER)
    assert PAPER in {p.payable_id for p in build_snapshot(env.conn, 1, env.clock.today()).payables}
    retry = txn(env, "debit", 18_000_000, OCT(12), "ASHIRWAD PAPER SUPPLIERS", "RETRY1")
    result = match_debit(env.conn, retry, window_days=3, clock=env.clock)
    assert result.outcome == f"linked to bill {PAPER}, already PAID"


# --- reviewer B, C2: a return email honours the owner's link ------------------------------


def _review_then_owner_paid(env, reference=REF):
    plan_and_approve(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "SOMEONE ELSE", reference)  # no name match: REVIEW
    with writer.atomic(env.conn):  # as the reconcile_txn job runs it
        match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert status(env, "payable", PAPER) == "REVIEW"
    return t


def test_a_return_reopens_a_review_bill_the_owner_marked_paid(web):
    env, client, csrf = web
    t = _review_then_owner_paid(env)
    plan_now(env, "t")
    post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))})
    assert env.conn.execute("SELECT matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()[0] == t
    cand = notice(env)
    with writer.atomic(env.conn):
        result = handle_failure(env.conn, cand, window_days=3, clock=env.clock)
    assert result.outcome == f"bill {PAPER} REOPENED"
    assert status(env, "bank_txn", t) == "REVERSED"
    assert PAPER in {p.payable_id for p in build_snapshot(env.conn, 1, env.clock.today()).payables}


def test_a_return_with_a_same_amount_twin_leaves_the_linked_debit_for_the_case(web):
    # Round 2: with a second approved bill of the same amount in the window, the
    # return matches two bills. The owner-linked debit must not be reversed while
    # its bill stays PAID: cash would be overstated by the bill's amount.
    env, client, csrf = web
    t = _review_then_owner_paid(env)
    plan_now(env, "t")
    post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))})
    from app.domain.models import PayableNew

    twin = writer.create_payable(PayableNew(business_id=1, party_id=2, amount_paise=18_000_000,
                                            due_date=OCT(13), priority="normal"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "CONFIRMED", "owner:1", "t", None, conn=env.conn,
                      expected_version=twin.version, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "PLANNED", "planner", "t", None, conn=env.conn,
                      fields={"planned_date": OCT(13)}, clock=env.clock)
    writer.transition(EntityRef("payable", twin.id), "PAYMENT_EXPECTED", "owner:1", "t", None, conn=env.conn,
                      expected_version=twin.version + 2, clock=env.clock)
    cand = notice(env)
    with writer.atomic(env.conn):
        result = handle_failure(env.conn, cand, window_days=3, clock=env.clock)
    assert result.outcome == "failure matches 2 bills: failed_payment case"
    assert status(env, "bank_txn", t) == "UNMATCHED"  # left for the owner, still lowering the balance
    assert status(env, "payable", PAPER) == "PAID"
    calc = build_snapshot(env.conn, 1, env.clock.today()).accounts[0].calculated_paise
    assert calc == 62_000_000 - 18_000_000  # the paid bill's money is still counted as gone


def test_a_reversed_debit_is_never_linked_when_the_owner_marks_paid(web):
    env, client, csrf = web
    t = _review_then_owner_paid(env)
    writer.transition(EntityRef("bank_txn", t), "REVERSED", "reconciler", "returned", None, conn=env.conn,
                      clock=env.clock)
    plan_now(env, "t")
    post(client, f"/payables/{PAPER}/mark-paid", csrf, {"version": str(version(env, PAPER))})
    row = env.conn.execute("SELECT status, matched_txn_id FROM payable WHERE id = ?", (PAPER,)).fetchone()
    assert tuple(row) == ("PAID", None)  # still counted as money to leave


# --- reviewer B, M1 / D16: known limit KL-1, pinned ---------------------------------------


def test_kl1_a_debit_that_does_not_name_match_an_owner_paid_bill_is_counted_twice(env):
    # D16: no auto-link on a name mismatch (the name rule is a security control).
    # The debit stays UNMATCHED with a case for the owner, and the bill still
    # counts: cash is understated, never overstated, until the owner links it
    # (CHG-022; cleared in tests/test_owner_explains_debit.py::test_kl1_cleared_...).
    from app.jobs.replan import replan

    plan_and_approve(env, PAPER)
    _owner_paid(env, PAPER)
    t = txn(env, "debit", 18_000_000, OCT(12), "NEFT DR 0012 ASHIRWAD PAP")
    result = match_debit(env.conn, t, window_days=3, clock=env.clock)
    assert status(env, "bank_txn", t) == "UNMATCHED" and status(env, "payable", PAPER) == "PAID"
    assert result.case_ids and cases(env)[0]["kind"] == "ambiguous_match"
    run_id = replan(env.conn, 1, triggered_by="t", clock=env.clock)
    lowest = env.conn.execute("SELECT lowest_balance_paise FROM plan_run WHERE id = ?", (run_id,)).fetchone()[0]
    assert lowest == 18_300_000 - 18_000_000  # both the debit and the bill: KL-1


# --- reviewer B, minors: link_payment and the new writer functions' checks ----------------


def test_link_payment_bumps_the_version_and_refuses_bad_links(env):
    plan_and_approve(env, PAPER)
    _owner_paid(env, PAPER)
    v = version(env, PAPER)
    credit = txn(env, "credit", 18_000_000, OCT(12), "X")
    with pytest.raises(IllegalTransition, match="not a debit"):
        writer.link_payment(PAPER, credit, "reconciler", "x", None, conn=env.conn, clock=env.clock)
    reversed_ = txn(env, "debit", 18_000_000, OCT(12), "X", "R1")
    writer.transition(EntityRef("bank_txn", reversed_), "REVERSED", "reconciler", "r", None, conn=env.conn,
                      clock=env.clock)
    with pytest.raises(IllegalTransition, match="reversed"):
        writer.link_payment(PAPER, reversed_, "reconciler", "x", None, conn=env.conn, clock=env.clock)
    good = txn(env, "debit", 18_000_000, OCT(12), "X", "R2")
    writer.link_payment(PAPER, good, "reconciler", "x", None, conn=env.conn, clock=env.clock)
    assert version(env, PAPER) == v + 1
    twin = add_paid_twin(env)
    with pytest.raises(IllegalTransition, match="already pays bill"):
        writer.link_payment(twin, good, "reconciler", "x", None, conn=env.conn, clock=env.clock)
    other = add_second_business_bill_paid(env)
    with pytest.raises(IllegalTransition, match="not a debit of this business"):
        writer.link_payment(other, good, "reconciler", "x", None, conn=env.conn, clock=env.clock)


def add_paid_twin(env):
    from app.domain.models import PayableNew

    twin = writer.create_payable(PayableNew(business_id=1, party_id=1, amount_paise=18_000_000,
                                            due_date=OCT(14), priority="normal"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    env.conn.execute("UPDATE payable SET status = 'PAID' WHERE id = ?", (twin.id,))
    env.conn.commit()
    return twin.id


def add_second_business_bill_paid(env):
    bill = add_second_business(env)
    env.conn.execute("UPDATE payable SET status = 'PAID' WHERE id = ?", (bill,))
    env.conn.commit()
    return bill


@pytest.mark.parametrize("actor", ["planner", "reconciler", "pipeline", "owner:3"])
def test_the_new_owner_writer_functions_refuse_system_actors_and_other_owners(env, actor):
    if actor == "owner:3":
        add_second_business(env)
    from app.jobs.replan import replan

    replan(env.conn, 1, triggered_by="t", clock=env.clock)
    option_id = env.conn.execute("SELECT id FROM shortfall_option LIMIT 1").fetchone()[0]
    calls = [
        lambda: writer.update_business_settings(1, {"horizon_days": 7}, actor, "x", None, conn=env.conn,
                                                clock=env.clock),
        lambda: writer.set_priority(EntityRef("payable", 5), "critical", actor, "x", None, conn=env.conn,
                                    expected_version=version(env, 5), clock=env.clock),
        lambda: writer.choose_option(option_id, actor, "x", None, conn=env.conn, clock=env.clock),
    ]
    for call in calls:
        with pytest.raises(ActorNotAllowed):
            call()


# --- reviewer B, C3: the demo clock across processes on Windows ---------------------------


def test_the_demo_clock_retries_while_another_process_holds_the_file(tmp_path, monkeypatch):
    from pathlib import Path

    clock = DemoClock(tmp_path / DEMO_CLOCK_FILE, datetime(2026, 10, 12, 9, tzinfo=TIMEZONE))
    clock.set(datetime(2026, 10, 13, 9, tzinfo=TIMEZONE))
    real_read, real_replace = Path.read_text, Path.replace
    busy = {"read": 3, "replace": 3}

    def flaky(kind, real):
        def op(self, *a, **kw):
            if busy[kind]:
                busy[kind] -= 1
                raise PermissionError(32, "being used by another process")
            return real(self, *a, **kw)
        return op

    monkeypatch.setattr(Path, "read_text", flaky("read", real_read))
    monkeypatch.setattr(Path, "replace", flaky("replace", real_replace))
    assert clock.now() == datetime(2026, 10, 13, 9, tzinfo=TIMEZONE)
    clock.set(datetime(2026, 10, 15, 9, tzinfo=TIMEZONE))
    assert clock.now() == datetime(2026, 10, 15, 9, tzinfo=TIMEZONE) and busy == {"read": 0, "replace": 0}


def test_a_demo_clock_that_stays_locked_is_a_plain_refusal(tmp_path, monkeypatch):
    env, _ = make_web_env(tmp_path)
    settings = env.settings.model_copy(update={"demo_now": "2026-10-12T09:00:00+05:30"})
    client = TestClient(create_app(settings, app_config=env.app_config))
    csrf = login(client)

    def locked(self, *a, **kw):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr("app.clock._shared", lambda op, **kw: locked(None))
    monkeypatch.setattr("app.clock.DemoClock.now", lambda self: datetime(2026, 10, 12, 9, tzinfo=TIMEZONE))
    r = post(client, "/demo/time", csrf, {"to": "2026-10-15T09:00"})
    assert r.status_code == 409 and "did not move" in r.text
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'poll_mail'").fetchone()[0] == 0  # rolled back
    env.conn.close()


def test_advance_rolls_back_its_jobs_when_the_clock_cannot_move(tmp_path, monkeypatch):
    # The jobs are enqueued first and rolled back on the same connection if the
    # clock can't be set, so the caller's connection is left clean.
    e = make_env(tmp_path)
    clock = clock_for("2026-10-12T09:00:00+05:30", tmp_path / "files")

    def locked(self, at):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr(DemoClock, "set", locked)
    with pytest.raises(PermissionError):
        demo.advance(e.conn, clock, datetime(2026, 10, 20, 9, tzinfo=TIMEZONE))
    assert not e.conn.in_transaction
    assert e.conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 0
    e.conn.close()


def test_moving_past_a_monday_keys_the_plan_by_that_monday(tmp_path):
    e = make_env(tmp_path)
    clock = clock_for("2026-10-12T09:00:00+05:30", tmp_path / "files")
    demo.advance(e.conn, clock, datetime(2026, 10, 20, 9, tzinfo=TIMEZONE))  # Tue 20, crossing Mon 19 07:00
    key = e.conn.execute("SELECT idempotency_key FROM job WHERE kind = 'monday_plan'").fetchone()[0]
    assert key == "monday_plan:1:2026-10-19"
    assert statuses(e)  # the ledger is untouched
    e.conn.close()
