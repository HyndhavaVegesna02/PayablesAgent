"""A chosen early_receipt still pending shows as chosen, not as a fresh option
(batch 4 plan, CHG-023; the PO's batch 3 UX note)."""

import re
from datetime import date, timedelta

import pytest

from app.web import repo
from tests.web_helpers import current_run, login, make_web_env, plan_now, post

LABEL = "Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct"


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _choose_nandi(client, csrf):
    page = client.get("/attention").text
    option_id = re.search(re.escape(LABEL) + r".*?/options/(\d+)/choose", page, re.S).group(1)
    assert post(client, f"/options/{option_id}/choose", csrf).status_code == 303


def test_after_a_replan_the_chosen_request_shows_as_pending_without_a_choose_button(web):
    env, client, csrf = web
    _choose_nandi(client, csrf)
    env.clock.advance(timedelta(days=3))  # Thu 15: a new plan, new options
    plan_now(env, "event:thursday")
    page = client.get("/attention").text
    article = page.split(LABEL)[1].split("</article>")[0]
    assert "Chosen on Mon 12 Oct: waiting for Nandi Foods to pay ₹2,00,000 by Fri 16 Oct" in article
    assert "/choose" not in article


def test_once_the_asked_date_passes_unpaid_it_is_offered_again_with_a_note(web):
    env, client, csrf = web
    _choose_nandi(client, csrf)
    plan_now(env, "event:replan")
    run_id = current_run(env)["id"]
    later = repo.options(env.conn, 1, run_id, today=date(2026, 10, 17))
    nandi = next(o for o in later if o.kind == "early_receipt")
    assert nandi.pending is None and nandi.asked_note == "Asked by Fri 16 Oct; not received"
    now = repo.options(env.conn, 1, run_id, today=date(2026, 10, 12))
    assert next(o for o in now if o.kind == "early_receipt").pending is not None


def test_a_receivable_already_received_is_not_pending(web):
    env, client, csrf = web
    _choose_nandi(client, csrf)
    plan_now(env, "event:replan")
    env.conn.execute("UPDATE receivable SET confidence = 'CONFIRMED' WHERE id = 2")
    env.conn.commit()
    opts = repo.options(env.conn, 1, current_run(env)["id"], today=date(2026, 10, 12))
    assert all(o.pending is None and o.asked_note is None for o in opts)
