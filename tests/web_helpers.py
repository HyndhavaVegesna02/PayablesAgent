"""A seeded worked-example database behind the real web app, for web tests.
The app shares the test's FakeClock (Mon 12 Oct 2026, 09:00)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.worker_helpers import Env, make_mail_env

OWNER = ("owner@example.test", "owner-demo-pass")
HELPER = ("helper@example.test", "helper-demo-pass")
_TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')
_META = re.compile(r'<meta name="csrf-token" content="([^"]*)">')


def make_web_env(tmp_path: Path) -> tuple[Env, TestClient]:
    env = make_mail_env(tmp_path)
    env.settings = env.settings.model_copy(update={"session_secret": "test-session-secret"})
    app = create_app(env.settings, clock=env.clock, app_config=env.app_config)
    return env, TestClient(app)


def login(client: TestClient, who: tuple[str, str] = OWNER) -> str:
    """Logs in and returns the session's CSRF token."""
    page = client.get("/login")
    token = _TOKEN.search(page.text).group(1)
    r = client.post("/login", data={"email": who[0], "password": who[1], "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    return csrf_of(client.get("/add").text)


def csrf_of(html: str) -> str:
    return _META.search(html).group(1)


def post(client: TestClient, path: str, csrf: str, data: dict | None = None, **kw):
    return client.post(path, data={**(data or {}), "csrf_token": csrf}, follow_redirects=False, **kw)


def plan_now(env: Env, triggered_by: str = "monday") -> int:
    """The Monday plan, as the worker's monday_plan job would make it."""
    from app.jobs.replan import replan

    return replan(env.conn, 1, triggered_by=triggered_by, clock=env.clock)


_VERSION = re.compile(r'name="(version_\d+)" value="(\d+)"')
_APPROVE = re.compile(r"/plans/(\d+)/approve")


def approve_form(html: str) -> tuple[int, dict[str, str]]:
    """The run id and version fields of the page's Approve form."""
    return int(_APPROVE.search(html).group(1)), dict(_VERSION.findall(html))


def statuses(env: Env) -> dict[int, str]:
    return dict(env.conn.execute("SELECT id, status FROM payable ORDER BY id").fetchall())


def version(env: Env, payable_id: int) -> int:
    return env.conn.execute("SELECT version FROM payable WHERE id = ?", (payable_id,)).fetchone()[0]


def current_run(env: Env):
    return env.conn.execute("SELECT * FROM plan_run WHERE is_current = 1").fetchone()


def plan_lines(env: Env) -> dict[int, tuple[str, str | None]]:
    run = current_run(env)
    return {r[0]: (r[1], r[2]) for r in env.conn.execute(
        "SELECT payable_id, decision, pay_on FROM plan_line WHERE plan_run_id = ?", (run["id"],))}


def owner_events(env: Env, after_id: int = 0) -> list[tuple[str, str]]:
    return [tuple(r) for r in env.conn.execute(
        "SELECT event_type, actor FROM event WHERE id > ? AND actor LIKE 'owner:%' ORDER BY id", (after_id,))]


def last_event_id(env: Env) -> int:
    return env.conn.execute("SELECT COALESCE(MAX(id), 0) FROM event").fetchone()[0]


def table_counts(env: Env) -> dict[str, int]:
    tables = [r[0] for r in env.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: env.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def add_second_business(env: Env) -> int:
    """Business 2 with owner 3 and one confirmed bill; returns that bill's id."""
    from datetime import date

    from app.domain.models import PayableNew
    from app.ledger import writer
    from app.ledger.writer import EntityRef
    from fixtures.seed import _password_hash

    env.conn.execute("INSERT INTO business (id, name, safety_amount_paise) VALUES (2, 'Other Works', 100000)")
    env.conn.execute("INSERT INTO app_user (id, business_id, email, role, password_hash) VALUES "
                     "(3, 2, 'other@example.test', 'owner', ?)", (_password_hash("other-pass"),))
    env.conn.commit()
    p = writer.create_payable(PayableNew(business_id=2, amount_paise=500_000, due_date=date(2026, 10, 20),
                                         priority="normal"), actor="owner:3", reason="test", source_ref=None,
                              conn=env.conn, clock=env.clock)
    writer.transition(EntityRef("payable", p.id), "CONFIRMED", "owner:3", "test", None, conn=env.conn,
                      expected_version=p.version, clock=env.clock)
    return p.id


def page_text(html: str) -> str:
    """The page as a reader sees it: tags removed, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def day_row(html: str, iso: str) -> str:
    """The text of one day's row under Payments by day on the week page."""
    return page_text(html.split(f'data-day="{iso}">')[1].split('<li class="day')[0].split("</ol>")[0])
