"""Full-workflow runs (batch 7, CHG-027): a scripted fortnight, Mon 12 to Sun
25 Oct 2026, played through the real system as the owner and the helper use
it.

- **The web app** is the real FastAPI app, driven over HTTP (Starlette's
  TestClient). The owner and the helper log in. Every action is a form the
  page itself rendered, posted with the page's CSRF token, so a button the
  page doesn't show can't be pressed.
- **The worker** is the real one: `default_handlers(backend)` run by
  `process_one`, on its own database connection.
- **Time** is the demo clock that the app and the worker share. The owner
  moves it with the demo form (`POST /demo/time`), which also polls the mail
  and makes Monday's plan, as in a demo.
- **Mail** is the test inbox. An email is copied into the run's inbox folder
  when its step says so, and is read once the clock passes its Date header.
- **Owner alerts** go through the real `send_alert` job to a capturing SMTP
  stand-in, so each email the owner would get is kept and checked.

Each run starts from a freshly migrated and seeded database (`make reseed`),
in a temp dir. Every step lists its checks: what was expected, what the
system shows, PASS or FAIL. The runs themselves are in evals/workflow_runs.py.

    python -m evals.workflow --ai fixtures [--run A|B] [--runs N] [--out docs/evals]"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.ai.client import Backend
from app.ai.fixture_backend import FIXTURE_AGENT_INBOX, FIXTURE_INBOX, FIXTURE_UPLOADS
from app.clock import TIMEZONE, clock_for
from app.config import AppConfig, Settings
from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from app.jobs import alerts
from app.jobs.replan import replan
from app.main import create_app
from app.worker import default_handlers, process_one
from fixtures.seed import BUSINESS_ID, DEV_HELPER_PASSWORD, DEV_OWNER_PASSWORD, HELPER_EMAIL, OWNER_EMAIL, seed

ROOT = Path(__file__).resolve().parent.parent
START = "2026-10-12T09:00:00+05:30"  # Mon 12 Oct 2026, the worked example's Monday
MAX_JOBS = 500  # per drain: a run that queues more is looping


class StepFailed(Exception):
    """An action the run needs could not be done (no such form, a refusal)."""


# --- the browser: forms as the page renders them ---------------------------------------------------


@dataclass
class Form:
    action: str
    fields: dict[str, Any]  # what a submit sends as it stands: hidden and text inputs, checked boxes
    checkboxes: dict[str, str]  # every checkbox's name -> value, checked or not
    radios: dict[str, list[str]]  # every radio group's name -> its values
    buttons: list[tuple[str, str, str]]  # (name, value, label)


class _Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[Form] = []
        self._button: list[str] | None = None
        self._select: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "form":
            self.forms.append(Form(a.get("action", ""), {}, {}, {}, []))
        elif not self.forms:
            return
        elif tag == "input":
            f, kind, name = self.forms[-1], a.get("type", "text"), a.get("name")
            if not name:
                return
            if kind == "checkbox":
                f.checkboxes[name] = a.get("value", "on")
                if "checked" in a:  # boxes sharing a name (payment days) send a list
                    have = f.fields.get(name)
                    value = a.get("value", "on")
                    f.fields[name] = value if have is None else [*([have] if isinstance(have, str) else have), value]
            elif kind == "submit":
                f.buttons.append((name, a.get("value", ""), a.get("value", "")))
            elif kind == "radio":
                f.radios.setdefault(name, []).append(a.get("value", "on"))
                if "checked" in a:
                    f.fields[name] = a.get("value", "on")
            elif kind != "file":
                f.fields[name] = a.get("value", "")
        elif tag == "button":
            self._button = [a.get("name", ""), a.get("value", ""), ""]
        elif tag == "select":
            self._select = a.get("name")
        elif tag == "option" and self._select and ("selected" in a or self._select not in self.forms[-1].fields):
            self.forms[-1].fields[self._select] = a.get("value", "")
        elif tag == "textarea" and a.get("name"):
            self.forms[-1].fields[a["name"]] = ""

    def handle_data(self, data: str) -> None:
        if self._button is not None:
            self._button[2] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._button is not None and self.forms:
            self.forms[-1].buttons.append((self._button[0], self._button[1], self._button[2].strip()))
            self._button = None
        elif tag == "select":
            self._select = None


def forms(html: str) -> list[Form]:
    p = _Forms()
    p.feed(html)
    return p.forms


class Browser:
    """One person's session on the web app."""

    def __init__(self, app, who: str) -> None:
        self.client = TestClient(app)
        self.who = who
        self.last: Any = None

    def get(self, path: str) -> str:
        r = self.client.get(path)
        if r.status_code != 200:
            raise StepFailed(f"{self.who}: GET {path} gave {r.status_code}")
        return r.text

    def login(self, email: str, password: str) -> None:
        (f,) = [f for f in forms(self.get("/login")) if f.action == "/login"]
        r = self.client.post("/login", data={**f.fields, "email": email, "password": password},
                             follow_redirects=False)
        if r.status_code != 303:
            raise StepFailed(f"{self.who}: login gave {r.status_code}")

    def form(self, page: str, action: str, where: dict[str, str] | None = None) -> Form:
        found = [f for f in forms(self.get(page)) if f.action == action
                 and all(f.fields.get(k) == v for k, v in (where or {}).items())]
        if not found:
            raise StepFailed(f"{self.who}: {page} shows no form for {action}")
        return found[0]

    def submit(self, page: str, action: str, values: dict[str, str] | None = None, *, button: str | None = None,
               tick: tuple[str, ...] = (), pick: dict[str, str] | None = None, files: dict | None = None,
               ok: tuple[int, ...] = (303,), where: dict[str, str] | None = None) -> Any:
        """Fills the page's form for `action` and submits it: `values` typed
        into its fields, the boxes in `tick` ticked, the radio values in `pick`
        chosen, and the button whose label contains `button` pressed."""
        f = self.form(page, action, where)
        unknown = [k for k in (values or {}) if k not in f.fields and k not in f.checkboxes]
        if unknown:
            raise StepFailed(f"{self.who}: the form for {action} has no field {unknown}")
        data = {**f.fields, **(values or {})}
        for name in tick:
            if name not in f.checkboxes:
                raise StepFailed(f"{self.who}: the form for {action} has no box {name}")
            data[name] = f.checkboxes[name]
        for name, value in (pick or {}).items():
            if value not in f.radios.get(name, []):
                raise StepFailed(f"{self.who}: the form for {action} offers no {name}={value}: {f.radios}")
            data[name] = value
        if button is not None:
            match = [b for b in f.buttons if button.lower() in b[2].lower()]
            if not match:
                raise StepFailed(f"{self.who}: no button {button!r} in the form for {action}: {f.buttons}")
            if match[0][0]:
                data[match[0][0]] = match[0][1]
        r = self.client.post(action, data=data, files=files, follow_redirects=False)
        self.last = r
        if r.status_code not in ok:
            raise StepFailed(f"{self.who}: POST {action} gave {r.status_code}: {_text(r.text)[:300]}")
        return r


def _text(html: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# --- the run's world -----------------------------------------------------------------------------


class CapturedSMTP:
    """Stands in for smtplib.SMTP: keeps every message the alert job sends."""

    sent: list[EmailMessage] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host

    def __enter__(self) -> CapturedSMTP:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def starttls(self, *a: Any, **k: Any) -> None:
        return None

    def login(self, *a: Any, **k: Any) -> None:
        return None

    def send_message(self, msg: EmailMessage) -> None:
        type(self).sent.append(msg)

    def quit(self) -> None:
        return None


@dataclass
class Check:
    id: str
    expected: Any
    actual: Any
    why: str

    @property
    def ok(self) -> bool:
        return self.actual == self.expected


@dataclass
class Step:
    n: int
    at: str
    actor: str
    action: str
    checks: list[Check] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(c.ok for c in self.checks)


class Run:
    """One fortnight: the app, the worker, the clock, the inbox and the record."""

    def __init__(self, tmp: Path, backend: Backend, app_config: AppConfig, *, fixtures_mode: bool) -> None:
        self.tmp = tmp
        self.fixtures_mode = fixtures_mode
        db = tmp / "workflow.db"
        (tmp / "inbox").mkdir()
        self.settings = Settings(
            _env_file=None, database_path=str(db), data_dir=str(tmp / "files"), trace_dir=str(tmp / "traces"),
            fernet_key=Fernet.generate_key().decode(), test_inbox_path=str(tmp / "inbox"), mail_source="eml_folder",
            session_secret="workflow-run", demo_now=START, demo_ai="fixtures" if fixtures_mode else "",
            smtp_host="smtp.capture.invalid", smtp_port=587, alert_from="alerts@payablesagent.example")
        self.app_config = app_config
        self.clock = clock_for(self.settings.demo_now, self.settings.data_dir)
        apply_migrations(db)  # make reseed: a fresh database, seeded, with its first plan
        self.conn = write_connection(db)
        seed(self.conn, self.clock)
        replan(self.conn, BUSINESS_ID, triggered_by="seed", clock=self.clock)
        self.conn.commit()
        CapturedSMTP.sent = []
        self.handlers = {**default_handlers(backend), **alerts.handlers(smtp_factory=CapturedSMTP)}
        app = create_app(self.settings, clock=self.clock, app_config=app_config)
        self.owner = Browser(app, "owner")
        self.owner.login(OWNER_EMAIL, DEV_OWNER_PASSWORD)
        self.helper = Browser(app, "helper")
        self.helper.login(HELPER_EMAIL, DEV_HELPER_PASSWORD)
        self.steps: list[Step] = []
        self.should_stop: Callable[[], str | None] = lambda: None

    # the world moves
    def drain(self) -> None:
        for _ in range(MAX_JOBS):
            reason = self.should_stop()
            if reason:
                raise StepFailed(f"stopped: {reason}")
            if not process_one(self.conn, self.handlers, clock=self.clock, settings=self.settings,
                               app_config=self.app_config):
                return
        raise StepFailed(f"more than {MAX_JOBS} jobs in one drain: the run is looping")

    def move_to(self, when: str) -> None:
        """The owner moves the demo clock (the Settings page's demo form); the worker catches up."""
        self.owner.submit("/settings", "/demo/time", {"to": when})
        self.drain()

    def deliver(self, *names: str) -> None:
        for name in names:
            folder = FIXTURE_AGENT_INBOX if (FIXTURE_AGENT_INBOX / name).is_file() else FIXTURE_INBOX
            shutil.copy(folder / name, self.settings.test_inbox_path)

    def upload(self, name: str) -> None:
        """The helper uploads a file on the Add page."""
        content = (FIXTURE_UPLOADS / name).read_bytes()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".wav": "audio/wav", ".pdf": "application/pdf"}[
            Path(name).suffix]
        self.helper.submit("/add", "/uploads", files={"file": (name, content, mime)})
        self.drain()

    def now(self) -> datetime:
        return self.clock.now().astimezone(TIMEZONE)

    # reading what the system holds
    def one(self, sql: str, args: tuple = ()) -> Any:
        row = self.conn.execute(sql, args).fetchone()
        return None if row is None else (row[0] if len(row) == 1 else tuple(row))

    def rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        return [tuple(r) for r in self.conn.execute(sql, args)]

    # the record
    @contextmanager
    def step(self, actor: str, action: str) -> Iterator[Step]:
        s = Step(len(self.steps) + 1, f"{self.now():%a %d %b %H:%M}", actor, action)
        self.steps.append(s)
        try:
            yield s
        except StepFailed as e:
            s.error = str(e)
        except Exception as e:  # noqa: BLE001 - a crash fails the step, and the run goes on to report it
            s.error = f"{type(e).__name__}: {e}"
        finally:
            s.at = f"{self.now():%a %d %b %H:%M}"  # when the step's checks were read

    def sent(self) -> list[EmailMessage]:
        """The owner alerts sent so far (captured)."""
        return list(CapturedSMTP.sent)

    def expect(self, check_id: str, actual: Any, expected: Any, why: str = "") -> None:
        self.steps[-1].checks.append(Check(check_id, expected, actual, why))

    def close(self) -> None:
        self.conn.close()


# --- running and reporting --------------------------------------------------------------------------


@dataclass
class Result:
    run: str
    title: str
    steps: list[Step]
    alerts: list[dict[str, str]]
    metrics: dict[str, Any]
    stopped: str | None = None

    @property
    def ok(self) -> bool:
        return self.stopped is None and all(s.ok for s in self.steps)


def play(name: str, backend: Backend, app_config: AppConfig, *, fixtures_mode: bool = True,
         should_stop: Callable[[], str | None] = lambda: None) -> Result:
    from evals import metrics
    from evals.workflow_runs import RUNS

    title, script = RUNS[name]
    with tempfile.TemporaryDirectory(prefix=f"workflow-{name}-") as tmp_name:
        run = Run(Path(tmp_name), backend, app_config, fixtures_mode=fixtures_mode)
        run.should_stop = should_stop
        try:
            script(run)
        finally:
            sent = [{"to": m["To"], "subject": m["Subject"], "body": m.get_content()} for m in CapturedSMTP.sent]
            m = metrics.collect(metrics.trace_steps(run.settings.trace_dir), run.conn)
            run.close()
    return Result(name, title, run.steps, sent, m, should_stop())


def _cell(v: Any) -> str:
    text = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
    return text.replace("|", "\\|").replace("\n", " ")[:160]


def markdown(results: list[Result], meta: dict[str, Any]) -> str:
    r0 = results[0]
    out = [f"# Workflow run {r0.run}: {r0.title}", "",
           "| Mode | Model | Prompt version | Commit | Date | Repeats | Model calls | Cost µUSD |",
           "|---|---|---|---|---|---|---|---|",
           f"| {meta['mode']} | {meta['model']} | {meta['prompt_version']} | {meta['commit']} | {meta['date']} "
           f"| {len(results)} | {sum(r.metrics['ai_calls'] for r in results)} "
           f"| {sum(r.metrics['cost_micro_usd'] for r in results)} |", ""]
    if meta["mode"] == "fixtures":
        out += ["Fixture mode: every model reply is canned (fixtures/ai_replies.json), so the run is "
                "deterministic and costs nothing. It shows the system end to end, not the model.", ""]
    for i, r in enumerate(results, 1):
        steps_ok = sum(s.ok for s in r.steps)
        checks = [c for s in r.steps for c in s.checks]
        out += [f"## Repeat {i}: {'PASS' if r.ok else 'FAIL'}", "",
                f"{steps_ok} of {len(r.steps)} steps passed; {sum(c.ok for c in checks)} of {len(checks)} checks."
                + (f" Stopped: {r.stopped}." if r.stopped else ""), "",
                "| # | When | Who | Step | Check | Expected | Actual | Result |", "|---|---|---|---|---|---|---|---|"]
        for s in r.steps:
            if s.error:
                out.append(f"| {s.n} | {s.at} | {s.actor} | {_cell(s.action)} | (the step) | done "
                           f"| {_cell(s.error)} | **FAIL** |")
            for j, c in enumerate(s.checks):
                head = f"| {s.n} | {s.at} | {s.actor} | {_cell(s.action)}" if j == 0 and not s.error else "| | | |"
                out.append(f"{head} | `{c.id}` | {_cell(c.expected)} | {_cell(c.actual)} | "
                           f"{'PASS' if c.ok else '**FAIL**'} |")
        if i == 1:
            out += ["", "### Why each expected value is what it is", ""]
            out += [f"- **{s.n}. `{c.id}`:** {c.why}" for s in r.steps for c in s.checks if c.why]
            out += ["", "### The owner alerts the run sent (captured, never delivered)", ""]
            out += [f"- **{a['subject']}**: {_cell(a['body'])}" for a in r.alerts] or ["- none"]
        out.append("")
    return "\n".join(out)


def write(results: list[Result], meta: dict[str, Any], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    stem = f"workflow-{results[0].run}-{meta['date'][:10]}" + ("" if meta["mode"] == "fixtures" else f"-{meta['mode']}")
    (out / f"{stem}.md").write_text(markdown(results, meta), encoding="utf-8", newline="\n")
    data = {"meta": meta, "repeats": [
        {"ok": r.ok, "stopped": r.stopped, "metrics": r.metrics, "alerts": r.alerts,
         "steps": [{"n": s.n, "at": s.at, "actor": s.actor, "action": s.action, "error": s.error,
                    "checks": [{"id": c.id, "expected": c.expected, "actual": c.actual, "ok": c.ok, "why": c.why}
                               for c in s.checks]} for s in r.steps]} for r in results]}
    (out / f"{stem}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
                                      encoding="utf-8", newline="\n")
    return out / f"{stem}.md"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from app.ai.fixture_backend import FixtureBackend
    from app.clock import SystemClock
    from evals import report, runner
    from evals.workflow_runs import RUNS

    p = argparse.ArgumentParser(prog="python -m evals.workflow", description="Play the scripted fortnights.")
    p.add_argument("--ai", choices=["fixtures", "live"], required=True)
    p.add_argument("--run", choices=sorted(RUNS), action="append", help="only this run (default: all)")
    p.add_argument("--runs", type=int, default=1, help="repeats of each run (default 1)")
    p.add_argument("--out", type=Path, default=ROOT / "docs" / "evals")
    p.add_argument("--yes-spend", action="store_true", help="required with --ai live")
    args = p.parse_args(argv)
    config, config_hash = runner.load_config()
    guard = None
    if args.ai == "live":
        from evals.budget import live_backend

        guard = live_backend(config, confirmed=args.yes_spend)  # one guard for the whole invocation
    failed = 0
    for name in args.run or sorted(RUNS):
        results = []
        for _ in range(args.runs):
            if guard is not None and guard.should_stop():
                break
            results.append(play(name, guard if guard is not None else FixtureBackend(), config,
                                fixtures_mode=guard is None,
                                should_stop=guard.should_stop if guard is not None else lambda: None))
        if not results:
            continue
        meta = {"run": name, "mode": args.ai, "model": config.model.id, "prompt_version": config.prompts.version,
                "config_sha256": config_hash, "commit": report.git_commit(),
                "date": SystemClock().now().isoformat(timespec="seconds"),
                "budget": guard.summary() if guard else None}
        path = write(results, meta, args.out)
        failed += sum(not r.ok for r in results)
        print(f"run {name}: {sum(r.ok for r in results)}/{len(results)} passed; report: {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
