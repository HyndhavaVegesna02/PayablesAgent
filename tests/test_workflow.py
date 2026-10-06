"""Full-workflow runs (batch 7, CHG-027): the two scripted fortnights play
through the real web app, worker and demo clock, and every step's checks
hold in fixture mode. The harness presses only buttons a page shows, and a
failed check or a broken step fails the run and the report says so."""

import json

import pytest

from app.ai.fixture_backend import FixtureBackend
from app.config import load_app_config
from evals import workflow
from evals.workflow import Browser, Check, Result, Step, StepFailed, forms
from evals.workflow_runs import RUNS

CONFIG = load_app_config(workflow.ROOT / "config.yaml")


@pytest.mark.parametrize("name", sorted(RUNS))
def test_the_run_holds_at_every_step_in_fixture_mode(name):
    r = workflow.play(name, FixtureBackend(), CONFIG)
    broken = [(s.n, s.action, s.error, [(c.id, c.expected, c.actual) for c in s.checks if not c.ok])
              for s in r.steps if not s.ok]
    assert broken == []
    assert all(s.checks for s in r.steps), "every step has an explicit check"
    assert [c.id for s in r.steps for c in s.checks if not c.why] == [], "every expected value says where it comes from"
    assert r.alerts and {a["to"] for a in r.alerts} == {"owner@example.test"}


def test_the_runs_cover_what_the_po_asked_for():
    import inspect

    from evals import workflow_runs

    a, b = inspect.getsource(workflow_runs.run_a), inspect.getsource(workflow_runs.run_b)
    for text in ("1,83,000", "early_receipt", "handwritten-bill-ganesh.png", "voice-note-sharma.wav",
                 '"/entries"', "3,83,000", "explain-plan-note", "audit-trail-email-to-bill-to-plan",
                 "pf-esi-paid-by-its-payee-words", "gst-debit-needs-the-owner", "first-bank-details-asked",
                 "due-date-flagged-not-guessed", "due-date-marked-on-the-form"):
        assert text in a, text
    for text in ("one-bill-not-two", "password-never-stored", "payment-returned", "recovered-from-mail",
                 "checking-then-ok", "RAMESH K", "refused-without-the-tick", "injection-changed-nothing",
                 "d18-floor", "split-in-two", "first-details-wait-for-the-owner"):
        assert text in b, text


def test_a_repeat_starts_from_a_fresh_database():
    first = workflow.play("A", FixtureBackend(), CONFIG)
    again = workflow.play("A", FixtureBackend(), CONFIG)
    assert [(s.action, [(c.id, c.actual) for c in s.checks]) for s in first.steps] == \
           [(s.action, [(c.id, c.actual) for c in s.checks]) for s in again.steps]


# --- the browser presses only what the page shows ---------------------------------------------------

PAGE = """<form action="/x" method="post"><input type="hidden" name="csrf_token" value="t">
<input name="amount" value="₹95,000"><input type="checkbox" name="days" value="MON" checked>
<input type="checkbox" name="days" value="THU" checked><input type="checkbox" name="alias" value="1">
<input type="radio" name="payable_id" value="4"><input type="radio" name="payable_id" value="7">
<select name="priority"><option value="statutory">s</option><option value="normal" selected>n</option></select>
<button type="submit" name="decision" value="paid">This paid the chosen bill</button></form>"""


def test_a_form_is_read_as_the_browser_would_send_it():
    (f,) = forms(PAGE)
    assert f.action == "/x"
    assert f.fields == {"csrf_token": "t", "amount": "₹95,000", "days": ["MON", "THU"], "priority": "normal"}
    assert f.checkboxes == {"days": "THU", "alias": "1"} and f.radios == {"payable_id": ["4", "7"]}
    assert f.buttons == [("decision", "paid", "This paid the chosen bill")]


class _Page:
    def __init__(self, html, status=200):
        self.text, self.status_code = html, status


class _Client:
    def __init__(self):
        self.posted = []

    def get(self, path):
        return _Page(PAGE)

    def post(self, path, data=None, files=None, follow_redirects=False):
        self.posted.append((path, data))
        return _Page("", 303)


def _browser():
    b = Browser.__new__(Browser)
    b.client, b.who, b.last = _Client(), "owner", None
    return b


def test_the_browser_sends_the_pages_token_and_what_was_chosen():
    b = _browser()
    b.submit("/page", "/x", tick=("alias",), pick={"payable_id": "7"}, button="This paid")
    ((path, data),) = b.client.posted
    assert path == "/x" and data["csrf_token"] == "t" and data["alias"] == "1"
    assert data["payable_id"] == "7" and data["decision"] == "paid"


@pytest.mark.parametrize("kw", [dict(button="Approve"), dict(values={"to": "x"}), dict(tick=("nope",)),
                                dict(pick={"payable_id": "9"})])
def test_the_browser_refuses_anything_the_page_does_not_offer(kw):
    b = _browser()
    with pytest.raises(StepFailed):
        b.submit("/page", "/x", **kw)
    with pytest.raises(StepFailed):
        b.submit("/page", "/not-on-the-page")
    assert b.client.posted == []


# --- a failure is reported as one ---------------------------------------------------------------------


def test_a_failed_check_or_a_broken_step_fails_the_run_and_the_report_shows_it(tmp_path):
    good = Step(1, "Mon 12 Oct 09:00", "owner", "opens the plan", [Check("lowest", 18_300_000, 18_300_000, "TDD")])
    bad = Step(2, "Mon 12 Oct 12:00", "bank", "the debit arrives", [Check("paid", "PAID", "PAYMENT_EXPECTED", "")])
    broken = Step(3, "Tue 13 Oct 12:00", "owner", "confirms", [], error="owner: /attention shows no form")
    r = Result("A", "t", [good, bad, broken], [], {"ai_calls": 0, "cost_micro_usd": 0})
    assert not bad.ok and not broken.ok and not r.ok
    meta = {"run": "A", "mode": "fixtures", "model": "m", "prompt_version": "v", "config_sha256": "0" * 64,
            "commit": "abc1234", "date": "2026-10-03T22:00:00+05:30", "budget": None}
    md_path = workflow.write([r], meta, tmp_path)
    md = md_path.read_text(encoding="utf-8")
    assert md_path.name == "workflow-A-2026-10-03.md"
    assert "## Repeat 1: FAIL" in md and "| `paid` | PAID | PAYMENT_EXPECTED | **FAIL** |" in md
    assert "owner: /attention shows no form | **FAIL** |" in md and "abc1234" in md
    data = json.loads(md_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["repeats"][0]["ok"] is False and data["meta"]["commit"] == "abc1234"


def test_live_mode_will_not_start_without_yes_spend():
    with pytest.raises(SystemExit, match="--yes-spend"):
        workflow.main(["--ai", "live", "--run", "A"])


def test_make_workflow_runs_both_or_one_with_repeats():
    text = (workflow.ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = text.split("\nworkflow:\n", 1)[1].splitlines()[0]
    assert "python -m evals.workflow --ai $(or $(AI),fixtures)" in recipe
    assert "$(if $(RUN),--run $(RUN))" in recipe and "$(if $(N),--runs $(N))" in recipe


def test_the_committed_workflow_reports_passed_and_say_where_they_came_from():
    folder = workflow.ROOT / "docs" / "evals" / "4-end-to-end-workflows"
    for name in sorted(RUNS):
        (path,) = [p for p in sorted(folder.glob(f"workflow-{name}-*.json")) if not p.stem.endswith("-live")]
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["meta"]["mode"] == "fixtures" and data["meta"]["run"] == name
        assert data["meta"]["commit"] != "unknown" and "+uncommitted" not in data["meta"]["commit"]
        assert all(r["ok"] for r in data["repeats"])
        assert "## Repeat 1: PASS" in path.with_suffix(".md").read_text(encoding="utf-8")
