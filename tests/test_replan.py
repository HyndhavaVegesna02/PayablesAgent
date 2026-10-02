"""Replan persistence and the planner's state moves (batch 2 plan, CHG-013
AC2-AC5), on the seeded worked example: Mon 12 Oct 2026, ₹6,20,000 cash."""

import hashlib
import json
from datetime import date, timedelta

import pytest

from app.db.read import build_snapshot
from app.domain.states import ActorNotAllowed, AgentActorRefused, IllegalTransition
from app.jobs import queue
from app.jobs.replan import enqueue_replan, replan
from app.ledger import writer
from app.ledger.writer import EntityRef
from app.planner.plan import PLANNER_VERSION, canonical_json
from tests.planner_fixtures import ORIGINAL_PLAN
from tests.worker_helpers import make_env

PAY_DAYS = {1: "2026-10-12", 2: "2026-10-15", 3: "2026-10-15", 4: "2026-10-19"}


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


def _replan(env, triggered_by="event:1"):
    return replan(env.conn, 1, triggered_by=triggered_by, clock=env.clock, trace_run_id="job-9-attempt-1")


def _bills(env):
    return {
        r["id"]: (r["status"], r["planned_date"])
        for r in env.conn.execute("SELECT id, status, planned_date FROM payable ORDER BY id")
    }


def _events(env, event_type):
    return env.conn.execute(
        "SELECT * FROM event WHERE event_type = ? ORDER BY id", (event_type,)
    ).fetchall()


# --- AC2 / AC3: what one replan stores ------------------------------------------


def test_a_replan_stores_the_worked_example_plan(env):
    snapshot = build_snapshot(env.conn, 1, env.clock.today())
    run_id = _replan(env, "monday")

    run = env.conn.execute("SELECT * FROM plan_run WHERE id = ?", (run_id,)).fetchone()
    assert run["business_id"] == 1
    assert run["triggered_by"] == "monday"
    assert run["created_at"] == env.clock.now().isoformat()
    assert run["inputs_sha256"] == hashlib.sha256(canonical_json(snapshot)).hexdigest()
    assert run["planner_version"] == PLANNER_VERSION
    assert (run["opening_cash_paise"], run["lowest_balance_paise"], run["lowest_on"]) == (
        62_000_000, 18_300_000, "2026-10-22",
    )
    assert (run["valid"], run["is_current"]) == (0, 1)

    days = env.conn.execute(
        "SELECT day, balance_paise FROM plan_day WHERE plan_run_id = ? ORDER BY day", (run_id,)
    ).fetchall()
    assert [d["balance_paise"] for d in days] == ORIGINAL_PLAN
    assert (days[0]["day"], days[-1]["day"]) == ("2026-10-12", "2026-10-25")

    lines = {
        r["payable_id"]: (r["decision"], r["pay_on"])
        for r in env.conn.execute("SELECT * FROM plan_line WHERE plan_run_id = ?", (run_id,))
    }
    assert lines == {**{k: ("PAY", v) for k, v in PAY_DAYS.items()}, 5: ("ESCALATE", None)}

    opts = env.conn.execute(
        "SELECT kind, params_json, lowest_balance_paise, meets_rule FROM shortfall_option "
        "WHERE plan_run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    assert [(o["kind"], o["lowest_balance_paise"], o["meets_rule"]) for o in opts] == [
        ("early_receipt", 38_300_000, 1), ("split", 25_000_000, 1), ("authorise_breach", 18_300_000, 0),
    ]
    split = json.loads(opts[1]["params_json"])
    assert split == {"payable_id": 5, "pay_now_paise": 5_300_000, "rest_paise": 6_700_000,
                     "rest_due": "2026-10-26"}
    # the split's what-if run uses payable id -5; nothing but real bills is stored
    stored = {r[0] for r in env.conn.execute("SELECT payable_id FROM plan_line")}
    assert stored <= {r[0] for r in env.conn.execute("SELECT id FROM payable")}


def test_params_json_is_canonical(env):
    run_id = _replan(env)
    for (text,) in env.conn.execute("SELECT params_json FROM shortfall_option WHERE plan_run_id = ?", (run_id,)):
        assert text == canonical_json(json.loads(text)).decode()


def test_only_the_latest_plan_is_current(env):
    first = _replan(env)
    second = _replan(env)
    current = env.conn.execute(
        "SELECT id FROM plan_run WHERE business_id = 1 AND is_current = 1"
    ).fetchall()
    assert [r["id"] for r in current] == [second]
    assert env.conn.execute("SELECT is_current FROM plan_run WHERE id = ?", (first,)).fetchone()[0] == 0


def test_the_four_paid_bills_move_to_planned_and_prime_chem_stays_confirmed(env):
    run_id = _replan(env)
    assert _bills(env) == {
        **{k: ("PLANNED", v) for k, v in PAY_DAYS.items()}, 5: ("CONFIRMED", None),
    }
    planned = _events(env, "PAYABLE_PLANNED")
    assert [e["entity_id"] for e in planned] == [1, 2, 3, 4]
    for e in planned:
        assert e["actor"] == "planner"
        assert e["source_ref"] == f"plan_run:{run_id}"
        assert e["trace_run_id"] == "job-9-attempt-1"


def test_the_planned_event_carries_part_1s_rule_check(env):
    _replan(env)
    paper = _events(env, "PAYABLE_PLANNED")[0]
    # Prime Chem's escalated ₹1,20,000 is not paid by this plan, so it is not in
    # the projected minimum: from Mon 12 Oct the lowest is ₹3,03,000 on Mon 19 Oct.
    assert paper["reason"] == (
        "Pay ₹1,80,000 on Mon 12 Oct: latest payment day on or before the due date (Wed 14 Oct)."
        " Projected minimum ₹3,03,000 on Mon 19 Oct; safety amount ₹2,50,000; rule check PASSED."
    )
    assert json.loads(paper["after_json"])["planned_date"] == "2026-10-12"


def test_a_statutory_bill_paid_through_a_breach_records_a_failed_rule_check(env):
    # ₹5,50,000 safety: statutory bills are placed first, so PF and ESI on Thu 15
    # leave ₹6,08,000 and GST on Mon 19 leaves ₹5,18,000: paid on time, below it.
    env.conn.execute("UPDATE business SET safety_amount_paise = 55000000 WHERE id = 1")
    env.conn.commit()
    _replan(env)
    gst = [e for e in _events(env, "PAYABLE_PLANNED") if e["entity_id"] == 4]
    assert len(gst) == 1
    assert gst[0]["reason"].endswith(
        "Projected minimum ₹5,18,000 on Mon 19 Oct; safety amount ₹5,50,000; rule check FAILED."
    )


def test_an_unchanged_replan_moves_nothing(env):
    _replan(env)
    before = env.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    _replan(env)
    assert env.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == before


# --- AC4: later replans ----------------------------------------------------------


def test_planned_bills_that_now_escalate_go_back_to_confirmed(env):
    _replan(env)
    # ₹5,00,000 safety: statutory bills are placed first (PF and ESI Thu 15, GST
    # Mon 19, leaving ₹5,18,000), so Electricity on Thu 15 would leave ₹4,83,000
    # and Paper on Mon 12 ₹4,40,000: both escalate. PF, ESI and GST stay planned.
    env.conn.execute("UPDATE business SET safety_amount_paise = 50000000 WHERE id = 1")
    env.conn.commit()
    run_id = _replan(env)

    decisions = dict(env.conn.execute(
        "SELECT payable_id, decision FROM plan_line WHERE plan_run_id = ?", (run_id,)
    ).fetchall())
    assert decisions == {1: "ESCALATE", 2: "PAY", 3: "ESCALATE", 4: "PAY", 5: "ESCALATE"}
    assert _bills(env) == {
        1: ("CONFIRMED", None), 2: ("PLANNED", "2026-10-15"), 3: ("CONFIRMED", None),
        4: ("PLANNED", "2026-10-19"), 5: ("CONFIRMED", None),
    }
    back = [e for e in _events(env, "PAYABLE_CONFIRMED") if e["actor"] == "planner"]
    assert [e["entity_id"] for e in back] == [1, 3]
    assert {e["source_ref"] for e in back} == {f"plan_run:{run_id}"}
    assert back[0]["reason"].startswith("Paying ₹1,80,000 on Mon 12 Oct takes the balance below")


def test_a_planned_bill_whose_pay_day_moves_gets_a_new_date_and_an_event(env):
    _replan(env)
    # Tue 13 Oct: Monday has passed, Paper (due Wed 14) has no payment day left
    # before its due date, so it moves to the next payment day, Thu 15 Oct.
    env.clock.advance(timedelta(days=1))
    run_id = _replan(env)

    assert _bills(env)[1] == ("PLANNED", "2026-10-15")
    moved = _events(env, "PAYABLE_REPLANNED")
    assert [e["entity_id"] for e in moved] == [1]
    assert moved[0]["actor"] == "planner"
    assert moved[0]["source_ref"] == f"plan_run:{run_id}"
    assert json.loads(moved[0]["before_json"])["planned_date"] == "2026-10-12"
    assert "on Thu 15 Oct" in moved[0]["reason"]
    assert {k: v for k, v in _bills(env).items() if k != 1} == {
        2: ("PLANNED", "2026-10-15"), 3: ("PLANNED", "2026-10-15"),
        4: ("PLANNED", "2026-10-19"), 5: ("CONFIRMED", None),
    }


def test_a_reopened_bill_is_planned_again(env):
    _replan(env)
    ref = EntityRef("payable", 1)
    v = env.conn.execute("SELECT version FROM payable WHERE id = 1").fetchone()[0]
    p = writer.transition(ref, "PAYMENT_EXPECTED", "owner:1", "approved", None, conn=env.conn,
                          expected_version=v, clock=env.clock)
    writer.transition(ref, "REOPENED", "reconciler", "returned", None, conn=env.conn,
                      expected_version=p.version, clock=env.clock)
    _replan(env)
    assert _bills(env)[1][0] == "PLANNED"


def test_a_failure_part_way_leaves_the_previous_plan_current_and_no_bill_moved(env, monkeypatch):
    first = _replan(env)
    env.conn.execute("UPDATE business SET safety_amount_paise = 50000000 WHERE id = 1")
    env.conn.commit()
    bills = _bills(env)

    def refuse(*a, **kw):
        raise RuntimeError("writer failed")

    monkeypatch.setattr(writer, "transition", refuse)
    with pytest.raises(RuntimeError):
        _replan(env)
    assert [r[0] for r in env.conn.execute("SELECT id FROM plan_run WHERE is_current = 1")] == [first]
    assert env.conn.execute("SELECT COUNT(*) FROM plan_run").fetchone()[0] == 1
    assert _bills(env) == bills


# --- set_planned_date ----------------------------------------------------------------


def _planned_paper(env):
    _replan(env)
    return env.conn.execute("SELECT version FROM payable WHERE id = 1").fetchone()[0]


def test_set_planned_date_bumps_the_version(env):
    v = _planned_paper(env)
    p = writer.set_planned_date(EntityRef("payable", 1), date(2026, 10, 15), "planner", "moved",
                                "plan_run:1", conn=env.conn, clock=env.clock)
    assert (p.version, p.planned_date) == (v + 1, date(2026, 10, 15))


@pytest.mark.parametrize("actor, error", [
    ("owner:1", ActorNotAllowed), ("reconciler", ActorNotAllowed), ("agent:case:1", AgentActorRefused),
])
def test_only_the_planner_may_move_a_planned_date(env, actor, error):
    _planned_paper(env)
    with pytest.raises(error):
        writer.set_planned_date(EntityRef("payable", 1), date(2026, 10, 15), actor, "x", None,
                                conn=env.conn, clock=env.clock)


def test_set_planned_date_refuses_a_bill_that_is_not_planned_or_the_same_date(env):
    _planned_paper(env)
    with pytest.raises(IllegalTransition):
        writer.set_planned_date(EntityRef("payable", 5), date(2026, 10, 22), "planner", "x", None,
                                conn=env.conn, clock=env.clock)  # Prime Chem is CONFIRMED
    with pytest.raises(IllegalTransition):
        writer.set_planned_date(EntityRef("payable", 1), date(2026, 10, 12), "planner", "x", None,
                                conn=env.conn, clock=env.clock)
    with pytest.raises(TypeError):
        writer.set_planned_date(EntityRef("payable", 1), "2026-10-15", "planner", "x", None,
                                conn=env.conn, clock=env.clock)


# --- AC5: queued replans absorb repeats -------------------------------------------------


def test_replan_requests_while_one_is_queued_make_one_job(env):
    a = enqueue_replan(env.conn, 1, "event:1", clock=env.clock)
    b = enqueue_replan(env.conn, 1, "event:2", clock=env.clock)
    env.conn.commit()
    assert a == b
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'replan'").fetchone()[0] == 1


def test_a_running_replan_does_not_absorb_a_new_request(env):
    a = enqueue_replan(env.conn, 1, "event:1", clock=env.clock)
    env.conn.commit()
    queue.claim_one(env.conn, kinds=["replan"], clock=env.clock)
    b = enqueue_replan(env.conn, 1, "event:2", clock=env.clock)
    assert a != b


def test_another_business_gets_its_own_replan(env):
    env.conn.execute("INSERT INTO business (id, name, safety_amount_paise) VALUES (2, 'B2', 0)")
    a = enqueue_replan(env.conn, 1, "event:1", clock=env.clock)
    b = enqueue_replan(env.conn, 2, "event:2", clock=env.clock)
    assert a != b
