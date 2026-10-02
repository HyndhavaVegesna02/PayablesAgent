"""Login, the session cookie and CSRF (batch 3 plan, CHG-006 S1; AC2, AC7)."""

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.main import create_app
from app.web import auth
from app.web.auth import SESSION_COOKIE, SessionSecretMissing
from tests.web_helpers import HELPER, OWNER, csrf_of, login, make_web_env, post


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def test_a_page_without_a_session_redirects_to_login(web):
    _, client = web
    r = client.get("/", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")


def test_an_action_without_a_session_is_401(web):
    _, client = web
    assert client.post("/logout").status_code in (200, 303)  # logout is harmless
    r = client.post("/payables/1/mark-paid", data={"csrf_token": "x"}, follow_redirects=False)
    assert r.status_code == 401


def test_the_owner_logs_in_and_gets_a_locked_down_cookie(web):
    _, client = web
    page = client.get("/login")
    token = page.text.split('name="csrf_token" value="')[1].split('"')[0]
    r = client.post("/login", data={"email": OWNER[0], "password": OWNER[1], "csrf_token": token},
                    follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/")
    cookie = [h for k, h in r.headers.multi_items() if k == "set-cookie" and h.startswith(SESSION_COOKIE)][0]
    flags = cookie.lower()
    assert "httponly" in flags and "samesite=lax" in flags and "path=/" in flags
    assert "secure" not in flags  # COOKIE_SECURE defaults to false for local http
    assert "max-age=43200" in flags


def test_a_helper_lands_on_add(web):
    _, client = web
    page = client.get("/login")
    token = page.text.split('name="csrf_token" value="')[1].split('"')[0]
    r = client.post("/login", data={"email": HELPER[0], "password": HELPER[1], "csrf_token": token},
                    follow_redirects=False)
    assert r.headers["location"] == "/add"


@pytest.mark.parametrize("email, password", [
    (OWNER[0], "wrong"), ("nobody@example.test", OWNER[1]), (OWNER[0], ""), ("", ""),
])
def test_a_wrong_login_gets_one_message_and_no_cookie(web, email, password):
    _, client = web
    token = client.get("/login").text.split('name="csrf_token" value="')[1].split('"')[0]
    r = client.post("/login", data={"email": email, "password": password, "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 401
    assert "Wrong email or password." in r.text
    assert SESSION_COOKIE not in r.cookies


def test_the_login_form_needs_its_csrf_token(web):
    _, client = web
    client.get("/login")
    r = client.post("/login", data={"email": OWNER[0], "password": OWNER[1], "csrf_token": "forged"},
                    follow_redirects=False)
    assert r.status_code == 403 and SESSION_COOKIE not in r.cookies


def test_email_case_does_not_matter(web):
    _, client = web
    login(client, (OWNER[0].upper(), OWNER[1]))


def test_a_tampered_cookie_is_no_session(web):
    _, client = web
    login(client)
    value = client.cookies.get(SESSION_COOKIE)
    client.cookies.set(SESSION_COOKIE, value[:-2] + ("A" if value[-1] != "A" else "B") + value[-1])
    assert client.get("/", follow_redirects=False).status_code == 303


def test_a_cookie_signed_with_another_secret_is_no_session(web):
    _, client = web
    forged = URLSafeTimedSerializer("not-our-secret", salt="pa-session").dumps({"uid": 1, "csrf": "x"})
    client.cookies.set(SESSION_COOKIE, forged)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_an_expired_cookie_is_no_session(web, monkeypatch):
    _, client = web
    login(client)
    assert client.get("/add").status_code == 200
    monkeypatch.setattr(auth, "SESSION_MAX_AGE", -1)  # every signature is now older than allowed
    assert client.get("/add", follow_redirects=False).status_code == 303


def test_a_cookie_for_a_user_that_no_longer_exists_is_no_session(web):
    env, client = web
    login(client, HELPER)
    env.conn.execute("DELETE FROM app_user WHERE id = 2")
    env.conn.commit()
    assert client.get("/add", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("how", ["missing", "wrong", "other_session"])
def test_a_post_without_this_sessions_csrf_token_is_403(web, tmp_path, how):
    env, client = web
    csrf = login(client)
    data = {}
    if how == "wrong":
        data["csrf_token"] = csrf[:-1] + ("x" if csrf[-1] != "x" else "y")
    elif how == "other_session":
        _, other = make_web_env(tmp_path / "other")
        data["csrf_token"] = login(other)
    r = client.post("/plans/1/approve", data=data, follow_redirects=False)
    assert r.status_code == 403
    assert env.conn.execute("SELECT COUNT(*) FROM event WHERE actor = 'owner:1' AND event_type = "
                            "'PAYABLE_PAYMENT_EXPECTED'").fetchone()[0] == 0


def test_the_csrf_header_htmx_sends_is_accepted(web):
    _, client = web
    csrf = login(client)
    r = client.post("/logout", headers={"X-CSRF-Token": csrf}, follow_redirects=False)
    assert r.status_code == 303


def test_logout_ends_the_session(web):
    _, client = web
    csrf = login(client)
    post(client, "/logout", csrf)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_pages_carry_the_csrf_token_for_htmx(web):
    _, client = web
    csrf = login(client)
    page = client.get("/add").text
    assert csrf_of(page) == csrf
    assert f'hx-headers=\'{{"X-CSRF-Token": "{csrf}"}}\'' in page


@pytest.mark.parametrize("secret", ["", "   "])
def test_the_app_refuses_to_start_without_a_session_secret(tmp_path, secret):
    env, _ = make_web_env(tmp_path)
    with pytest.raises(SessionSecretMissing) as e:
        create_app(env.settings.model_copy(update={"session_secret": secret}), clock=env.clock,
                   app_config=env.app_config)
    assert 'uv run python -c "import secrets; print(secrets.token_urlsafe(32))"' in str(e.value)
    env.conn.close()


def test_static_files_are_served_without_login(web):
    _, client = web
    assert client.get("/static/htmx.min.js").status_code == 200
    assert client.get("/static/pico.min.css").status_code == 200
    assert "https://" not in client.get("/login").text  # no CDN anywhere
