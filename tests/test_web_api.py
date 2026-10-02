"""GET /api/plan/current and POST /api/what-if (batch 3 plan, CHG-006 S2 and
S4; Q9: what-if writes nothing)."""

import pytest

from tests.web_helpers import HELPER, login, make_web_env, plan_now, table_counts


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def test_the_current_plan_as_json(web):
    _, client, _ = web
    plan = client.get("/api/plan/current").json()["plan"]
    assert (plan["lowest_balance_paise"], plan["lowest_on"], plan["valid"]) == (18_300_000, "2026-10-22", False)
    assert [(ln["payable_id"], ln["decision"], ln["pay_on"]) for ln in plan["lines"]] == [
        (1, "PAY", "2026-10-12"), (2, "PAY", "2026-10-15"), (3, "PAY", "2026-10-15"), (4, "PAY", "2026-10-19"),
        (5, "ESCALATE", None),
    ]
    assert len(plan["days"]) == 14 and plan["days"][0] == {"day": "2026-10-12", "balance_paise": 44_000_000}
    assert [o["kind"] for o in plan["options"]] == ["early_receipt", "split", "authorise_breach"]


def test_no_plan_is_null(tmp_path):
    env, client = make_web_env(tmp_path)
    login(client)
    assert client.get("/api/plan/current").json() == {"plan": None}
    env.conn.close()


def test_a_helper_gets_403_as_plain_text(web):
    _, client, _ = web
    login(client, HELPER)
    r = client.get("/api/plan/current")
    assert r.status_code == 403 and r.headers["content-type"].startswith("text/plain")


def test_what_if_nandi_pays_on_friday_reaches_the_worked_example_figure(web):
    env, client, csrf = web
    before = table_counts(env)
    changes = env.conn.total_changes
    r = client.post("/api/what-if", json={"receivable_dates": {"2": "2026-10-16"}}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert (plan["lowest_balance_paise"], plan["lowest_on"], plan["valid"]) == (38_300_000, "2026-10-22", True)
    assert r.json()["options"] == []
    assert table_counts(env) == before and env.conn.total_changes == changes


def test_what_if_can_drop_bills_and_change_the_safety_amount(web):
    _, client, csrf = web
    r = client.post("/api/what-if", json={"drop_payables": [5], "safety_paise": 30_000_000},
                    headers={"X-CSRF-Token": csrf})
    plan = r.json()["plan"]
    assert plan["lowest_balance_paise"] == 30_300_000 and plan["safety_paise"] == 30_000_000


@pytest.mark.parametrize("body", [
    {"receivable_dates": {"99": "2026-10-16"}}, {"receivable_dates": {"2": "16 Oct"}}, {"drop_payables": "5"},
    {"safety_paise": 1.5}, {"surprise": 1}, [1, 2],
])
def test_a_bad_what_if_is_409_and_writes_nothing(web, body):
    env, client, csrf = web
    before = table_counts(env)
    r = client.post("/api/what-if", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 409 and r.headers["content-type"].startswith("text/plain")
    assert table_counts(env) == before


def test_what_if_needs_the_csrf_header(web):
    _, client, _ = web
    assert client.post("/api/what-if", json={}).status_code == 403
