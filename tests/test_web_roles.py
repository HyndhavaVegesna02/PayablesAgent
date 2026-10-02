"""Every route has a role, checked on the server (batch 3 plan, CHG-006 AC2,
AC5): the route table matches the TDD's HTTP routes table minus Gmail, every
owner-only route refuses a helper with 403, and ids outside the user's
business are 404."""

import subprocess
import sys

import pytest
from fastapi.routing import APIRoute

from tests.web_helpers import HELPER, OWNER, add_second_business, login, make_web_env, post, statuses

OWNER_ONLY = ("owner",)
BOTH = ("owner", "helper")
ANYONE = None

# TDD Part 2, "HTTP routes", without the three Gmail routes (out of scope until
# the user sets up Gmail). Logout is POST only: a GET would let any page log the owner out.
TDD_ROUTES = {
    ("GET", "/login"): ANYONE,
    ("POST", "/login"): ANYONE,
    ("POST", "/logout"): ANYONE,
    ("GET", "/api/health"): ANYONE,
    ("GET", "/"): OWNER_ONLY,
    ("GET", "/attention"): OWNER_ONLY,
    ("GET", "/add"): BOTH,
    ("GET", "/accounts"): OWNER_ONLY,
    ("GET", "/settings"): OWNER_ONLY,
    ("POST", "/settings"): OWNER_ONLY,
    ("POST", "/uploads"): BOTH,
    ("POST", "/entries"): BOTH,
    ("POST", "/candidates/{candidate_id}/confirm"): OWNER_ONLY,
    ("POST", "/candidates/{candidate_id}/reject"): OWNER_ONLY,
    ("POST", "/plans/{run_id}/approve"): OWNER_ONLY,
    ("POST", "/payables/{payable_id}/mark-paid"): OWNER_ONLY,
    ("POST", "/options/{option_id}/choose"): OWNER_ONLY,
    ("POST", "/questions/{question_id}/answer"): OWNER_ONLY,
    ("POST", "/accounts/{account_id}/confirm-balance"): OWNER_ONLY,
    ("POST", "/documents/{document_id}/unlock"): OWNER_ONLY,
    ("POST", "/parties/{party_id}/bank-change"): OWNER_ONLY,
    ("GET", "/api/plan/current"): OWNER_ONLY,
    ("POST", "/api/what-if"): OWNER_ONLY,
}
OWNER_ROUTES = [k for k, v in TDD_ROUTES.items() if v == OWNER_ONLY]


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def _roles(route: APIRoute):
    found = [d.call.roles for d in route.dependant.dependencies if hasattr(d.call, "roles")]
    assert len(found) <= 1, route.path
    return tuple(found[0]) if found else None


def _api_routes(routes):
    # FastAPI wraps an included router (no prefixes are used here); walk into it.
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def test_the_route_table_is_the_tdd_table_with_a_role_on_every_route(web):
    _, client = web
    table = {}
    for route in _api_routes(client.app.routes):
        for method in route.methods - {"HEAD"}:
            table[(method, route.path)] = _roles(route)
    assert table == TDD_ROUTES


def _concrete(path: str) -> str:
    for name in ("candidate_id", "run_id", "payable_id", "option_id", "question_id", "account_id",
                 "document_id", "party_id"):
        path = path.replace("{" + name + "}", "1")
    return path


@pytest.mark.parametrize("method, path", OWNER_ROUTES)
def test_a_helper_gets_403_on_every_owner_only_route(web, method, path):
    env, client = web
    csrf = login(client, HELPER)
    before = statuses(env)
    if method == "GET":
        r = client.get(_concrete(path), follow_redirects=False)
    else:
        r = client.post(_concrete(path), data={"csrf_token": csrf}, headers={"X-CSRF-Token": csrf},
                        follow_redirects=False)
    assert r.status_code == 403
    assert statuses(env) == before


@pytest.mark.parametrize("method, path", OWNER_ROUTES)
def test_every_owner_only_route_needs_a_login(web, method, path):
    _, client = web
    r = client.request(method, _concrete(path), follow_redirects=False)
    assert r.status_code == (303 if method == "GET" and not path.startswith("/api/") else 401)


def test_the_helper_navigation_offers_only_add(web):
    _, client = web
    login(client, HELPER)
    page = client.get("/add").text
    assert 'href="/add"' in page
    for link in ('href="/"', 'href="/attention"', 'href="/accounts"', 'href="/settings"'):
        assert link not in page


def test_ids_from_another_business_are_404(web):
    env, client = web
    other_bill = add_second_business(env)
    csrf = login(client, OWNER)
    r = post(client, f"/payables/{other_bill}/mark-paid", csrf, {"version": "2"})
    assert r.status_code == 404
    assert env.conn.execute("SELECT status FROM payable WHERE id = ?", (other_bill,)).fetchone()[0] == "CONFIRMED"


def test_the_other_business_owner_sees_none_of_business_one(web):
    env, client = web
    add_second_business(env)
    login(client, ("other@example.test", "other-pass"))
    assert "Prime Chem" not in client.get("/settings").text
    assert "HDFC" not in client.get("/accounts").text
    assert client.post("/payables/5/mark-paid", data={"version": "2"},
                       headers={"X-CSRF-Token": login(client, ("other@example.test", "other-pass"))},
                       follow_redirects=False).status_code == 404


def test_starting_the_web_app_loads_no_ai_module():
    code = (
        "import sys\n"
        "from app.config import Settings\n"
        "from app.main import create_app\n"
        "create_app(Settings(_env_file=None, session_secret='x'))\n"
        "print(sorted(m for m in sys.modules if m == 'app.ai' or m.startswith('app.ai.')))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
