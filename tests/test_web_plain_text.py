"""AI-written and document-sourced text is shown as plain text everywhere
(batch 3 plan, CHG-006 AC4; TDD Part 1, "Messages"): autoescape is on, no
template or web module marks a value safe, and planted HTML renders escaped."""

import json
import re
from pathlib import Path

import pytest

from app.web.app import _env
from tests.web_helpers import login, make_web_env, plan_now, post

WEB = Path(__file__).resolve().parent.parent / "app" / "web"
SCRIPT = "<script>alert(1)</script>"
ATTRIBUTE = '" autofocus onfocus="alert(1)'
BANNED = [r"\|\s*safe\b", r"Markup\(", r"autoescape\s+false", r"\{%-?\s*raw", r"\|\s*e\s*\(\s*false"]


def test_autoescape_is_on():
    assert _env.autoescape is True


@pytest.mark.parametrize("path", sorted(p for p in WEB.rglob("*") if p.suffix in (".html", ".py")),
                         ids=lambda p: p.name)
def test_nothing_in_app_web_marks_a_value_safe(path):
    text = path.read_text(encoding="utf-8")
    for pattern in BANNED:
        assert not re.search(pattern, text), f"{path.name} matches {pattern}"


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    plan_now(env)
    csrf = login(client)
    yield env, client, csrf
    env.conn.close()


def _no_live_markup(page: str) -> None:
    assert SCRIPT not in page and "<img" not in page
    assert 'autofocus onfocus="alert(1)' not in page


def test_a_planted_vendor_name_is_escaped_on_every_page(web):
    env, client, csrf = web
    post(client, "/entries", csrf, {"kind": "bill", "party": SCRIPT, "amount": "1,000", "due_date": "2026-11-05",
                                    "invoice_number": ATTRIBUTE})
    for path in ("/add", "/attention"):
        page = client.get(path).text
        _no_live_markup(page)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&#34; autofocus onfocus=&#34;alert(1)" in client.get("/attention").text


def test_planted_text_in_a_plan_reason_a_question_and_an_extract_is_escaped(web):
    env, client, _ = web
    run_id = env.conn.execute("SELECT id FROM plan_run WHERE is_current = 1").fetchone()[0]
    env.conn.execute("UPDATE plan_line SET reason = ? WHERE plan_run_id = ? AND payable_id = 5",
                     ('<img src=x onerror="alert(1)">', run_id))
    env.conn.execute("INSERT INTO owner_question (business_id, kind, body_text, status) VALUES (1, 'explain_txn', ?, 'OPEN')",
                     (f"Debit from {SCRIPT}",))
    doc = env.conn.execute("INSERT INTO source_document (business_id, kind, content_sha256, received_at, status) "
                           "VALUES (1, 'email', 'x', '2026-10-12T09:00:00+05:30', 'PROCESSED')").lastrowid
    payload = {"doc_type": "bank_alert", "record": None,
               "extract": {"account_last4": "4821", "direction": "debit", "amount_text": ATTRIBUTE,
                           "txn_date": "2026-10-12", "counterparty": SCRIPT, "reference": None}}
    env.conn.execute("INSERT INTO candidate (source_document_id, record_type, payload_json, checks_json, status, "
                     "created_by, created_at) VALUES (?, 'txn', ?, ?, 'AWAITING_OWNER', 'pipeline', 'now')",
                     (doc, json.dumps(payload), json.dumps({"amount": f"failed: {SCRIPT}"})))
    env.conn.commit()
    week = client.get("/").text
    _no_live_markup(week)
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in week
    attention = client.get("/attention").text
    _no_live_markup(attention)
    assert attention.count("&lt;script&gt;") >= 3  # the question, the counterparty, the failed check
