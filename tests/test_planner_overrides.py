"""The planner honours the owner's overrides (batch 4 plan, CHG-021; PO
decisions D17, D18): an authorisation pays an escalated bill below the safety
amount down to the floor the owner saw, and lapses if the breach goes deeper;
a delay uses a flexible bill's grace days. The planner stays pure: overrides
arrive only through PlanSnapshot."""

from dataclasses import replace
from datetime import date

import pytest
from hypothesis import given, settings

from app.domain.states import ActorNotAllowed, IllegalTransition
from app.ledger import writer
from app.ledger.writer import EntityRef
from app.planner.options import options
from app.planner.plan import OverrideIn, PayableIn, plan
from tests.planner_fixtures import worked_example
from tests.test_planner_properties import snapshots
from tests.web_helpers import (
    current_run,
    last_event_id,
    login,
    make_web_env,
    owner_events,
    plan_lines,
    plan_now,
    post,
    statuses,
    version,
)

PRIME = 5
FLOOR = 18_300_000  # the lowest balance the owner saw: ₹1,83,000 on Thu 22 Oct


def _authorised(s, floor=FLOOR, payable_id=PRIME):
    return replace(s, overrides=(OverrideIn(payable_id, "authorise_breach", floor),))


def _line(result, payable_id):
    return next(ln for ln in result.lines if ln.payable_id == payable_id)


# --- the pure planner -------------------------------------------------------------------


def test_an_authorised_bill_is_paid_on_its_day_with_the_owners_reason():
    r = plan(_authorised(worked_example()))
    line = _line(r, PRIME)
    assert (line.decision, line.pay_on) == ("PAY", date(2026, 10, 22))
    assert line.reason.startswith("Pay ₹1,20,000 on Thu 22 Oct: authorised by the owner although it takes the "
                                  "balance below the safety amount")
    assert (r.lowest_balance_paise, r.valid, r.authorised, r.lapsed) == (FLOOR, False, (PRIME,), ())
    assert options(_authorised(worked_example()), r) == []  # not offered again


@pytest.mark.parametrize("floor", [FLOOR, FLOOR - 1, 0])
def test_an_equal_or_shallower_breach_stays_covered(floor):
    r = plan(_authorised(worked_example(), floor))
    assert _line(r, PRIME).decision == "PAY" and r.lapsed == ()


def test_a_deeper_breach_lapses_the_authorisation_and_escalates_again():
    s = worked_example()
    deeper = replace(s, payables=s.payables + (PayableIn(99, 1_300_000, date(2026, 10, 19), "statutory"),))
    r = plan(_authorised(deeper))
    line = _line(r, PRIME)
    assert line.decision == "ESCALATE" and r.lapsed == (PRIME,) and r.authorised == ()
    assert line.reason.endswith("Your authorisation covered a low of ₹1,83,000; the plan now goes to ₹1,70,000.")
    assert [o.kind for o in options(_authorised(deeper), r)][-1] == "authorise_breach"  # offered again


def test_a_delay_uses_the_grace_days_and_drops_the_discount():
    s = worked_example()
    flexible = replace(s.payables[-1], priority="flexible", grace_days=7, discount_paise=100_000,
                       discount_by=date(2026, 10, 20))
    s = replace(s, payables=s.payables[:-1] + (flexible,))
    (delay,) = [o for o in options(s, plan(s)) if o.kind == "delay_flexible"]
    r = plan(replace(s, overrides=(OverrideIn(PRIME, "delay_flexible"),)))
    # The same figures as the option's own what-if (here Thu 29 Oct, after the
    # horizon, so the bill waits), and the discount is gone.
    assert _line(r, PRIME) == _line(delay.plan, PRIME)
    assert (r.lowest_balance_paise, r.lowest_on, r.days) == (delay.lowest_balance_paise, delay.lowest_on,
                                                             delay.plan.days)
    assert _line(plan(s), PRIME).decision == "ESCALATE" and "discount" not in _line(r, PRIME).reason


@settings(max_examples=150, deadline=None)
@given(snapshots())
def test_property_no_overrides_means_no_change(s):
    plain = plan(replace(s, overrides=()))
    assert plain.authorised == () and plain.lapsed == ()
    assert all("authorised by the owner" not in ln.reason for ln in plain.lines)
    # overrides naming bills that are not in the snapshot change nothing at all
    stray = replace(s, overrides=(OverrideIn(10**6, "authorise_breach", 0), OverrideIn(10**6 + 1, "delay_flexible")))
    assert plan(stray) == plain


# --- the ledger: storage, events, ending -------------------------------------------------


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _authorise(env, client, csrf):
    page = client.get("/attention").text
    option_id = int(page.split("Authorise going below")[1].split("/options/")[1].split("/")[0])
    assert post(client, f"/options/{option_id}/choose", csrf).status_code == 303
    return option_id


def test_choosing_authorise_records_a_bounded_override_and_replans(web):
    env, client, csrf = web
    mark = last_event_id(env)
    option_id = _authorise(env, client, csrf)
    o = env.conn.execute("SELECT * FROM plan_override").fetchone()
    assert (o["payable_id"], o["kind"], o["floor_paise"], o["breach_on"], o["status"], o["shortfall_option_id"]) == (
        PRIME, "authorise_breach", FLOOR, "2026-10-22", "ACTIVE", option_id)
    assert ("PLAN_OVERRIDE_RECORDED", "owner:1") in owner_events(env, mark)
    assert plan_lines(env)[PRIME] == ("PAY", "2026-10-22") and statuses(env)[PRIME] == "PLANNED"
    page = client.get("/attention").text
    assert "Your choices in force" in page and "at or above ₹1,83,000" in page
    assert "Authorise going below" not in page  # not offered again
    assert "Prime Chem Industries ₹1,20,000 <small>(authorised below the safety amount)</small>" in client.get("/").text


def test_a_deeper_breach_lapses_the_override_with_an_event(web):
    env, client, csrf = web
    _authorise(env, client, csrf)
    from app.domain.models import PayableNew

    bill = writer.create_payable(PayableNew(business_id=1, amount_paise=1_300_000, due_date=date(2026, 10, 19),
                                            priority="statutory"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", bill.id), "CONFIRMED", "owner:1", "t", None, conn=env.conn,
                      expected_version=bill.version, clock=env.clock)
    plan_now(env, "event:new-bill")
    assert env.conn.execute("SELECT status FROM plan_override").fetchone()[0] == "LAPSED"
    ev = env.conn.execute("SELECT actor FROM event WHERE event_type = 'PLAN_OVERRIDE_LAPSED'").fetchone()
    assert ev[0] == "planner"
    assert plan_lines(env)[PRIME] == ("ESCALATE", None) and statuses(env)[PRIME] == "CONFIRMED"
    assert "Authorise going below" in client.get("/attention").text  # offered again


def test_the_owner_undoes_an_authorisation(web):
    env, client, csrf = web
    option_id = _authorise(env, client, csrf)
    mark = last_event_id(env)
    assert post(client, f"/options/{option_id}/choose", csrf, {"undo": "1"}).status_code == 303
    assert env.conn.execute("SELECT status FROM plan_override").fetchone()[0] == "ENDED"
    assert ("PLAN_OVERRIDE_ENDED", "owner:1") in owner_events(env, mark)
    assert plan_lines(env)[PRIME] == ("ESCALATE", None)
    assert post(client, f"/options/{option_id}/choose", csrf, {"undo": "1"}).status_code == 409


def test_an_override_ends_when_its_bill_is_paid(web):
    env, client, csrf = web
    _authorise(env, client, csrf)
    run_id = current_run(env)["id"]
    for bill in (1, 2, 3, 4):
        if statuses(env)[bill] == "PLANNED":
            writer.transition(EntityRef("payable", bill), "PAYMENT_EXPECTED", "owner:1", "t", f"plan_run:{run_id}",
                              conn=env.conn, expected_version=version(env, bill), clock=env.clock)
    writer.transition(EntityRef("payable", PRIME), "PAYMENT_EXPECTED", "owner:1", "t", None, conn=env.conn,
                      expected_version=version(env, PRIME), clock=env.clock)
    writer.transition(EntityRef("payable", PRIME), "PAID", "owner:1", "paid", None, conn=env.conn,
                      expected_version=version(env, PRIME), clock=env.clock)
    assert env.conn.execute("SELECT status FROM plan_override").fetchone()[0] == "ENDED"


def test_override_writes_are_the_owners_and_the_planners_only(web):
    env, _, _ = web
    with pytest.raises(ActorNotAllowed):
        writer.record_override(1, PRIME, "authorise_breach", "planner", "x", None, conn=env.conn,
                               floor_paise=0, clock=env.clock)
    with pytest.raises(ValueError, match="floor"):
        writer.record_override(1, PRIME, "authorise_breach", "owner:1", "x", None, conn=env.conn, clock=env.clock)
    o = writer.record_override(1, PRIME, "delay_flexible", "owner:1", "x", None, conn=env.conn, clock=env.clock)
    with pytest.raises(ActorNotAllowed):
        writer.end_override(o["id"], "LAPSED", "owner:1", "x", None, conn=env.conn, clock=env.clock)
    writer.end_override(o["id"], "ENDED", "owner:1", "x", None, conn=env.conn, clock=env.clock)
    with pytest.raises(IllegalTransition):
        writer.end_override(o["id"], "ENDED", "owner:1", "x", None, conn=env.conn, clock=env.clock)


def test_a_helper_cannot_undo(web):
    env, client, csrf = web
    option_id = _authorise(env, client, csrf)
    from tests.web_helpers import HELPER

    helper_csrf = login(client, HELPER)
    assert post(client, f"/options/{option_id}/choose", helper_csrf, {"undo": "1"}).status_code == 403
    assert env.conn.execute("SELECT status FROM plan_override").fetchone()[0] == "ACTIVE"


# --- batch 4 review round 1 ---------------------------------------------------------------


def test_c2_an_authorisations_own_knock_on_never_lapses_it():
    # Paying A lowers the curve, so B's early-payment discount no longer fits and B
    # is paid in full: the lowest drops, but nothing outside the authorisation changed.
    from app.planner.plan import AccountCash, PlanSnapshot

    s = PlanSnapshot(
        today=date(2026, 10, 12), horizon_days=14, payment_days=frozenset({0, 3}), safety_paise=1_000_000,
        accounts=(AccountCash(1, 2_000_000, None, False),),
        payables=(PayableIn(1, 1_200_000, date(2026, 10, 22), "normal"),
                  PayableIn(2, 500_000, date(2026, 10, 22), "flexible", discount_paise=50_000,
                            discount_by=date(2026, 10, 15))),
        inflows=(), commitments=(),
    )
    shown = plan(s)
    assert _line(shown, 1).decision == "ESCALATE"
    r = plan(replace(s, overrides=(OverrideIn(1, "authorise_breach", shown.lowest_balance_paise),)))
    assert r.lapsed == () and _line(r, 1).decision == "PAY"


def test_c3_a_lapse_keeps_the_bills_delay():
    # Electricity made flexible (3 grace days, so Thu 15 -> Mon 19) and large enough to
    # escalate; it carries both a delay and an authorisation, and a new statutory bill
    # deepens the breach. The authorisation lapses; the delay must still apply.
    s = worked_example()
    elec = replace(s.payables[2], priority="flexible", grace_days=3, amount_paise=12_000_000)
    s = replace(s, payables=tuple(elec if p.payable_id == 3 else p for p in s.payables))
    floor = plan(replace(s, overrides=(OverrideIn(3, "delay_flexible"),))).lowest_balance_paise
    deeper = replace(s, payables=s.payables + (PayableIn(99, 1_300_000, date(2026, 10, 19), "statutory"),))
    r = plan(replace(deeper, overrides=(OverrideIn(3, "authorise_breach", floor), OverrideIn(3, "delay_flexible"))))
    assert r.lapsed == (3,)
    assert r.days == plan(replace(deeper, overrides=(OverrideIn(3, "delay_flexible"),))).days
    assert r.days != plan(deeper).days  # so dropping the delay would show


def test_c4_an_approved_authorised_bill_is_still_covered():
    # The mainline flow: every earlier bill approved, then Prime approved under the authorisation.
    s = _authorised(worked_example())
    approved = tuple(replace(p, status="PAYMENT_EXPECTED", planned_date=day) for p, day in zip(
        s.payables, (date(2026, 10, 12), date(2026, 10, 15), date(2026, 10, 15), date(2026, 10, 19),
                     date(2026, 10, 22))))
    s = replace(s, payables=approved)
    r = plan(s)
    assert r.authorised == (PRIME,) and r.escalations == () and not r.valid
    assert options(s, r) == []  # not offered again while the authorisation covers the breach


def test_c1_the_run_that_lapses_an_authorisation_is_not_stale(web):
    env, client, csrf = web
    _authorise(env, client, csrf)
    from app.domain.models import PayableNew
    from app.db.read import build_snapshot
    from app.jobs.replan import inputs_sha256

    bill = writer.create_payable(PayableNew(business_id=1, amount_paise=1_300_000, due_date=date(2026, 10, 19),
                                            priority="statutory"),
                                 actor="owner:1", reason="t", source_ref=None, conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", bill.id), "CONFIRMED", "owner:1", "t", None, conn=env.conn,
                      expected_version=bill.version, clock=env.clock)
    plan_now(env, "event:new-bill")
    run = current_run(env)
    assert run["inputs_sha256"] == inputs_sha256(build_snapshot(env.conn, 1, env.clock.today()))
    page = client.get("/attention").text
    option_id = int(page.split("Authorise going below")[1].split("/options/")[1].split("/")[0])
    assert post(client, f"/options/{option_id}/choose", csrf).status_code == 303  # not refused as stale


def test_an_override_ends_when_its_bill_is_split_or_reopened(web):
    env, client, csrf = web
    _authorise(env, client, csrf)
    writer.split_payable(EntityRef("payable", PRIME), 5_000_000, date(2026, 11, 10), "owner:1", "split", None,
                         conn=env.conn, expected_version=version(env, PRIME), clock=env.clock)
    assert env.conn.execute("SELECT status FROM plan_override").fetchone()[0] == "ENDED"
    # REOPENED: an authorised bill approved, then its payment fails.
    o = writer.record_override(1, 4, "delay_flexible", "owner:1", "x", None, conn=env.conn, clock=env.clock)
    for to, actor in (("PAYMENT_EXPECTED", "owner:1"), ("REOPENED", "reconciler")):
        writer.transition(EntityRef("payable", 4), to, actor, "t", None, conn=env.conn,
                          expected_version=version(env, 4), clock=env.clock)
    row = env.conn.execute("SELECT status FROM plan_override WHERE id = ?", (o["id"],)).fetchone()
    assert row[0] == "ENDED"
    ev = env.conn.execute("SELECT actor FROM event WHERE event_type = 'PLAN_OVERRIDE_ENDED' "
                          "AND entity_id = ?", (o["id"],)).fetchone()
    assert ev[0] == "reconciler"


def test_choosing_a_delay_through_the_app_gives_the_options_figures(tmp_path):
    # Electricity made flexible with 3 grace days: due Fri 16 -> Mon 19, inside the horizon.
    env, client = make_web_env(tmp_path)
    env.conn.execute("UPDATE payable SET priority = 'flexible', grace_days = 3 WHERE id = 3")
    env.conn.commit()
    plan_now(env)
    csrf = login(client)
    opt = env.conn.execute("SELECT id, lowest_balance_paise FROM shortfall_option WHERE kind = 'delay_flexible'"
                           ).fetchone()
    mark = last_event_id(env)
    assert post(client, f"/options/{opt['id']}/choose", csrf).status_code == 303
    o = env.conn.execute("SELECT payable_id, kind, status FROM plan_override").fetchone()
    assert tuple(o) == (3, "delay_flexible", "ACTIVE")
    assert ("PLAN_OVERRIDE_RECORDED", "owner:1") in owner_events(env, mark)
    assert plan_lines(env)[3] == ("PAY", "2026-10-19")
    assert current_run(env)["lowest_balance_paise"] == opt["lowest_balance_paise"]
    assert post(client, f"/options/{opt['id']}/choose", csrf, {"undo": "1"}).status_code == 303
    assert plan_lines(env)[3] == ("PAY", "2026-10-15")
    env.conn.close()


def test_a_second_authorisation_is_measured_on_the_plan_the_owner_saw():
    # Re-review round 2: authorising A takes C's early-payment discount away, which
    # deepens the low; B then escalates and the owner authorises it at the low he saw
    # (with A applied). With nothing else changed, B must stay covered, and so must A.
    from app.planner.plan import AccountCash, InflowIn, PlanSnapshot

    s = PlanSnapshot(
        today=date(2026, 10, 12), horizon_days=14, payment_days=frozenset({0, 3}), safety_paise=1_000_000,
        accounts=(AccountCash(1, 3_000_000, None, False),),
        payables=(PayableIn(1, 2_500_000, date(2026, 10, 15), "normal"),
                  PayableIn(2, 2_800_000, date(2026, 10, 22), "normal"),
                  PayableIn(3, 500_000, date(2026, 10, 22), "flexible", discount_paise=50_000,
                            discount_by=date(2026, 10, 15))),
        inflows=(InflowIn(1, 3_000_000, date(2026, 10, 19), "COMMITTED"),), commitments=(),
    )
    first = plan(s)
    assert _line(first, 1).decision == "ESCALATE"
    a = OverrideIn(1, "authorise_breach", first.lowest_balance_paise)
    second = plan(replace(s, overrides=(a,)))
    assert second.lapsed == () and _line(second, 2).decision == "ESCALATE"
    b = OverrideIn(2, "authorise_breach", second.lowest_balance_paise)
    third = plan(replace(s, overrides=(a, b)))  # in the order chosen, as build_snapshot reads them
    assert third.lapsed == ()
    assert _line(third, 1).decision == "PAY" and _line(third, 2).decision == "PAY"
    assert third.lowest_balance_paise == second.lowest_balance_paise


def test_one_choice_covering_two_bills_is_measured_as_one():
    # Re-review round 3: one authorise choice records an override for each escalated
    # bill, all at the low of the same run. Paying A takes C's early-payment discount
    # away; that knock-on must not lapse B, chosen in the same breath.
    from app.planner.plan import AccountCash, PlanSnapshot

    s = PlanSnapshot(
        today=date(2026, 10, 12), horizon_days=14, payment_days=frozenset({0, 3}), safety_paise=1_000_000,
        accounts=(AccountCash(1, 2_000_000, None, False),),
        payables=(PayableIn(1, 1_200_000, date(2026, 10, 22), "normal"),
                  PayableIn(2, 1_100_000, date(2026, 10, 22), "normal"),
                  PayableIn(3, 500_000, date(2026, 10, 22), "flexible", discount_paise=50_000,
                            discount_by=date(2026, 10, 15))),
        inflows=(), commitments=(),
    )
    shown = plan(s)
    assert _line(shown, 1).decision == _line(shown, 2).decision == "ESCALATE"
    choice = tuple(OverrideIn(i, "authorise_breach", shown.lowest_balance_paise, choice_id=7) for i in (1, 2))
    r = plan(replace(s, overrides=choice))
    assert r.lapsed == ()
    assert _line(r, 1).decision == "PAY" and _line(r, 2).decision == "PAY"
