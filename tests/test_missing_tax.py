"""D11, MISSING tax amounts (batch 5 plan, S7). A statutory obligation whose
amount nobody knows yet has no payable, since the planner never invents an
amount. It asks the owner (ca_reminder), the plan says it may be optimistic
while the amount is missing, and once the owner gives the amount the
statutory bill is created and the plan counts it."""

from datetime import date

import pytest

from app.domain.models import TaxObligationNew
from app.domain.states import ActorNotAllowed
from app.ledger import writer
from tests.web_helpers import current_run, login, make_web_env, owner_events, plan_lines, plan_now, post

WARNING = "TDS 2026-09 amount missing (due Mon 19 Oct): plan may be optimistic"


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def missing(env, due=date(2026, 10, 19)):
    ob = writer.create_tax_obligation(
        TaxObligationNew(business_id=1, tax_type="TDS", period="2026-09", due_date=due, amount_paise=None,
                         amount_status="MISSING"),
        actor="owner:1", reason="TDS amount not known yet", source_ref=None, conn=env.conn, clock=env.clock)
    env.conn.commit()
    return ob


def question(env):
    return env.conn.execute("SELECT * FROM owner_question WHERE kind = 'ca_reminder' ORDER BY id DESC").fetchone()


def test_a_missing_amount_warns_beside_the_plan_and_never_enters_it(web):
    env, client = web
    plan_now(env)
    before = plan_lines(env)
    missing(env)
    plan_now(env, "event:tax")
    assert plan_lines(env) == before  # no amount was invented
    login(client)
    assert WARNING in client.get("/").text
    page = client.get("/attention").text
    assert "The TDS amount for 2026-09, due Mon 19 Oct, is missing." in page and 'name="amount_status"' in page


def test_a_missing_amount_due_after_the_horizon_does_not_warn(web):
    env, client = web
    plan_now(env)
    missing(env, due=date(2026, 11, 7))
    login(client)
    assert "amount missing" not in client.get("/").text


def test_the_owner_gives_the_amount_and_the_plan_counts_the_statutory_bill(web):
    env, client = web
    plan_now(env)
    ob = missing(env)
    csrf = login(client)
    r = post(client, f"/questions/{question(env)['id']}/answer", csrf, {"amount": "20,000", "amount_status": "ESTIMATED"})
    assert r.status_code == 303
    row = env.conn.execute("SELECT amount_paise, amount_status, payable_id FROM tax_obligation WHERE id = ?",
                           (ob.id,)).fetchone()
    assert tuple(row[:2]) == (2_000_000, "ESTIMATED") and row[2] is not None
    bill = env.conn.execute("SELECT amount_paise, priority, status, due_date FROM payable WHERE id = ?",
                            (row[2],)).fetchone()
    assert tuple(bill) == (2_000_000, "statutory", "PLANNED", "2026-10-19")  # confirmed, then planned by the replan
    assert row[2] in plan_lines(env) and current_run(env)["triggered_by"] != "monday"
    assert question(env)["status"] == "ANSWERED"
    assert ("TAX_OBLIGATION_AMOUNT_SET", "owner:1") in owner_events(env)
    assert WARNING not in client.get("/").text


def test_an_unreadable_amount_is_refused_and_the_amount_stays_missing(web):
    env, client = web
    plan_now(env)
    ob = missing(env)
    csrf = login(client)
    r = post(client, f"/questions/{question(env)['id']}/answer", csrf, {"amount": "about twenty"})
    assert r.status_code == 422 and "Enter the amount in rupees" in r.text
    status = env.conn.execute("SELECT amount_status FROM tax_obligation WHERE id = ?", (ob.id,)).fetchone()[0]
    assert status == "MISSING"


def test_only_the_owner_gives_a_tax_amount(web):
    env, _ = web
    ob = missing(env)
    with pytest.raises(ActorNotAllowed):
        writer.supply_tax_amount(ob.id, 2_000_000, "CONFIRMED", "pipeline", "x", None, conn=env.conn)
