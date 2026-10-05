"""explain_plan (batch 6, CHG-018): a replan gets a plain-text note of what
changed. Gemini's words are kept only if every amount and date in them is in
the plan diff; otherwise, and without AI, the note is a template built from
the diff. A replan that changed nothing gets no note and no AI call."""

import functools
from datetime import date

import pytest

from app.ai.client import AIUnavailable
from app.db.read import persisted_result
from app.domain.models import BankTxnNew
from app.domain.money import format_inr
from app.jobs.explain import handle_explain_plan
from app.ledger import writer
from app.planner.diff import diff
from app.planner.plan import format_day
from app.validate import PASSED
from app.validate.summary import check_summary
from tests.fake_ai import FakeBackend
from tests.web_helpers import login, make_web_env, plan_now
from tests.worker_helpers import run_all

AMOUNTS = frozenset({18_300_000, 38_300_000, -2_000_000})
DATES = frozenset({date(2026, 10, 12), date(2026, 10, 15)})  # Mon 12 Oct, Thu 15 Oct


@pytest.mark.parametrize("text", [
    "Lowest balance now ₹1,83,000 on Thu 15 Oct (was ₹3,83,000 on Mon 12 Oct).",
    "The low point moved to Rs.1,83,000.00 on 15 Oct; it was Rs 3,83,000 on 2026-10-12.",
    "It dips to 1,83,000 on Oct 15 and to -₹20,000 at worst, from 3,83,000 on 12/10.",
    "Nothing else changed.",
    "Paid by Thurs 15 Oct.",  # 'rs' inside a word is not rupees
    "It was ₹3,83,000, and now ₹1,83,000.",  # a comma after an amount is prose
    "It now dips to −₹20,000, an overdraft.",
])
def test_a_summary_using_only_the_diffs_numbers_passes(text):
    assert check_summary(text, AMOUNTS, DATES) == PASSED


@pytest.mark.parametrize("text, why", [
    ("Lowest balance now ₹1,84,000 on Thu 15 Oct.", "amount '₹1,84,000'"),
    ("Lowest balance now ₹1,83,000 on Fri 16 Oct.", "date 'Fri 16 Oct'"),
    ("Lowest balance now ₹1,83,000 on Wed 15 Oct.", "date 'Wed 15 Oct'"),  # the weekday disagrees
    ("Lowest balance now ₹1,83,000 on 15 Oct 2025.", "date '15 Oct 2025'"),
    ("Lowest balance now ₹1,83,000 after 2 bills.", "number '2'"),
    ("Lowest balance now -₹1,83,000.", "amount '-₹1,83,000'"),  # the diff has +₹1,83,000
    ("Lowest balance now ₹20,000 on Thu 15 Oct.", "amount '₹20,000'"),  # the diff has -₹20,000: an overdraft
    ("Lowest balance now –₹1,83,000.", "amount '–₹1,83,000'"),  # en dash
    ("Lowest balance now —₹1,83,000.", "amount '—₹1,83,000'"),  # em dash
    ("Lowest balance now －₹1,83,000.", "amount '－₹1,83,000'"),  # full-width minus
    ("Lowest balance now ‐1,83,000.", "amount '‐1,83,000'"),  # a bare amount after U+2010
    ("Lowest balance now minus ₹1,83,000.", "number in words 'minus'"),
    ("Lowest balance now (₹1,83,000).", "brackets"),
    ("Lowest is one lakh eighty-three thousand.", "number in words 'one'"),
    ("Down five percent.", "number in words 'five'"),
    ("Due on the sixteenth.", "number in words 'sixteenth'"),
    ("Pay it tomorrow.", "number in words 'tomorrow'"),
    ("A third is ⅓ of it.", "number in words 'third'"),
    ("About ⅓ of it.", "numeral '⅓'"),
    ("   ", "empty"),
    ("Lowest is 1,99,000 now.", "amount '1,99,000'"),
    ("Lowest balance <b>₹1,83,000</b>.", "markup"),
    ("See [the plan](http://x).", "markup"),
    ("Nothing changed. " * 40, "longer than 600"),
])
def test_a_summary_with_anything_not_in_the_diff_fails(text, why):
    verdict = check_summary(text, AMOUNTS, DATES)
    assert verdict.startswith("failed:") and why in verdict


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def _changed_plans(env):
    """Two plans with a ₹10,000 debit between them; returns both run ids."""
    first = plan_now(env)
    writer.create_bank_txn(
        BankTxnNew(account_id=1, direction="debit", amount_paise=1_000_000, txn_date=date(2026, 10, 12),
                   counterparty="CASH", dedup_key="test:cash", status="UNMATCHED"),
        actor="pipeline", reason="test", source_ref="test", conn=env.conn, clock=env.clock)
    second = plan_now(env, "event:test")
    env.conn.commit()
    return first, second


def _explain(env, backend):
    run_all(env, {"explain_plan": functools.partial(handle_explain_plan, backend=backend)})
    status = env.conn.execute("SELECT status FROM job WHERE kind = 'explain_plan'").fetchone()[0]
    assert status == "done"


def _summary(env, run_id):
    return tuple(env.conn.execute("SELECT summary_text, summary_source FROM plan_run WHERE id = ?",
                                  (run_id,)).fetchone())


def _true_note(env, first, second):
    a, b = (env.conn.execute("SELECT * FROM plan_run WHERE id = ?", (r,)).fetchone() for r in (first, second))
    return (f"A cash debit lowered the start to {format_inr(b['opening_cash_paise'])} from "
            f"{format_inr(a['opening_cash_paise'])}; the lowest balance is now {format_inr(b['lowest_balance_paise'])} "
            f"on {format_day(date.fromisoformat(b['lowest_on']))}.")


def test_replan_queues_explain_plan_against_the_plan_it_replaces(web):
    env, _ = web
    first, second = _changed_plans(env)
    (payload,) = [r[0] for r in env.conn.execute("SELECT payload_json FROM job WHERE kind = 'explain_plan'")]
    assert f'"plan_run_id": {second}' in payload and f'"previous_run_id": {first}' in payload


def test_the_stored_runs_diff_like_the_plans_themselves(web):
    env, _ = web
    first, second = _changed_plans(env)
    d = diff(persisted_result(env.conn, first), persisted_result(env.conn, second))
    assert [c.kind for c in d.changes][:2] == ["opening_cash", "lowest"]
    assert 61_000_000 in d.amounts_paise and 62_000_000 in d.amounts_paise


def test_a_stored_line_keeps_what_it_pays_after_a_discount(web):
    from app.db.read import build_snapshot
    from app.planner.plan import plan

    env, _ = web
    env.conn.execute("UPDATE payable SET discount_paise = 200000, discount_by = '2026-10-14' WHERE id = 1")
    first, second = _changed_plans(env)
    live = {ln.payable_id: ln.amount_paise for ln in plan(build_snapshot(env.conn, 1, env.clock.today())).lines}
    stored = {ln.payable_id: ln.amount_paise for ln in persisted_result(env.conn, second).lines}
    assert live[1] == 17_800_000 and stored == live  # ₹1,80,000 less the ₹2,000 discount
    # and a run stored before migration 0004 (no amount) reads the bill's amount
    env.conn.execute("UPDATE plan_line SET amount_paise = NULL WHERE plan_run_id = ?", (first,))
    assert {ln.payable_id: ln.amount_paise for ln in persisted_result(env.conn, first).lines}[1] == 18_000_000


def test_a_checked_gemini_note_is_kept(web):
    env, _ = web
    first, second = _changed_plans(env)
    note = _true_note(env, first, second)
    backend = FakeBackend().queue("PlanSummary", {"summary": note})  # nothing optional: one call expected
    _explain(env, backend)
    assert _summary(env, second) == (note, "gemini")
    assert backend.requests[0].thinking == "low"
    assert "Cash at the start now ₹6,10,000 (was ₹6,20,000)." in backend.requests[0].contents


@pytest.mark.parametrize("reply", [
    {"summary": "The start fell by ₹10,000."},  # worked out: not in the diff
    {"summary": "Cash fell <script>x</script>."},
    {"summary": "  "},  # empty: no note at all would hide the change
    {"note": "wrong shape"},  # a schema failure
    AIUnavailable("down", retryable=True),
])
def test_anything_else_falls_back_to_the_template(web, reply):
    env, _ = web
    _, second = _changed_plans(env)
    _explain(env, FakeBackend().queue("PlanSummary", reply))  # one reply, as queued
    text, source = _summary(env, second)
    assert source == "template" and text.startswith("Cash at the start now ₹6,10,000 (was ₹6,20,000).")


def test_without_ai_the_note_is_the_template(web):
    env, _ = web
    _, second = _changed_plans(env)
    _explain(env, None)
    assert _summary(env, second)[1] == "template"


def test_a_replan_that_changed_nothing_gets_no_note_and_no_call(web):
    env, _ = web
    plan_now(env)
    second = plan_now(env, "event:none")
    env.conn.commit()
    backend = FakeBackend()  # any call would fail the test
    _explain(env, backend)
    assert backend.requests == [] and _summary(env, second) == (None, None)


def test_the_first_plan_queues_no_explanation(web):
    env, _ = web
    plan_now(env)
    assert env.conn.execute("SELECT COUNT(*) FROM job WHERE kind = 'explain_plan'").fetchone()[0] == 0


def test_this_week_shows_the_note_as_plain_text(web):
    env, client = web
    env.conn.execute("UPDATE party SET name = '<b>Prime</b> Chem' WHERE id = 3")
    first, second = _changed_plans(env)
    env.conn.execute("UPDATE plan_run SET summary_text = ?, summary_source = 'template' WHERE id = ?",
                     ("<b>Prime</b> Chem: PAY on Thu 22 Oct (was ESCALATE).", second))
    env.conn.commit()
    login(client)
    page = client.get("/").text
    assert "What changed" in page and "&lt;b&gt;Prime&lt;/b&gt; Chem: PAY on Thu 22 Oct" in page
    assert "<b>Prime</b>" not in page
    assert "From the plan&#39;s own figures." in page


def test_the_owner_reads_decisions_in_plain_words_and_the_model_keeps_the_planners_terms():
    from app.jobs.explain import change_lines
    from app.planner.diff import Change, PlanDiff

    thu22 = date(2026, 10, 22)
    d = PlanDiff(changes=(
        Change("line_changed", 5, {"decision": "ESCALATE", "pay_on": None, "amount_paise": 12_000_000},
               {"decision": "PAY", "pay_on": thu22, "amount_paise": 12_000_000}),
        Change("line_added", 6, None, {"decision": "WAIT", "pay_on": None, "amount_paise": 1_200_000}),
        Change("line_removed", 7, {"decision": "PAY", "pay_on": thu22, "amount_paise": 500_000}, None),
    ), amounts_paise=frozenset(), dates=frozenset({thu22}))
    names = {5: "Prime Chem Industries", 6: "Sharma Packaging", 7: "Old Vendor"}
    assert change_lines(d, names) == [
        "Prime Chem Industries: PAY on Thu 22 Oct (was ESCALATE).",
        "Sharma Packaging ₹12,000: WAIT (new in the plan).",
        "Old Vendor: no longer in the plan (was PAY on Thu 22 Oct).",
    ]
    assert change_lines(d, names, owner_words=True) == [
        "Prime Chem Industries: now paid on Thu 22 Oct (was waiting for your decision).",
        "Sharma Packaging ₹12,000: waits (new in the plan).",
        "Old Vendor: no longer in the plan (was to be paid on Thu 22 Oct).",
    ]
