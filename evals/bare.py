"""The bare harness for the ablation (TDD Part 1, "Harness comparison"; batch 7,
CHG-010a, S6, D24): a naive agent loop on the same model and the same inputs.

What it has: every tool, write tools included, against its own scratch copy
of the seeded database; one growing chat history (every earlier step is
resent); a cap of 20 steps. What it does not have: rule checks, a case file,
escalation, a ledger writer, the planner. The model works out the balances and
the plan itself and gives them as its final answer.

The inputs are the full system's. The seeded state, written out as text, and
then the scenario's events in order: each email's text (and its attachments),
each upload, and each thing the owner did. The model is the same, and every
call is at medium thinking, the level of the full system's extract and
exception work. It is scored on the scenario's `outcome` checks (the same
SELECTs against its own database, and the plan it gave), exactly as the full
system is.

It writes its scratch database directly, with no ledger writer, by design: it
is the harness without one. It never touches the app's database
(tests/test_ledger_write_guard.py lists it, with this reason)."""

from __future__ import annotations

import email
import email.policy
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.client import AIUnavailable, Backend, Part, call
from app.ai.email_text import email_text
from app.ai.fixture_backend import FIXTURE_UPLOADS
from app.clock import TIMEZONE, FakeClock
from app.config import AppConfig
from app.domain.money import format_inr, parse_inr
from app.ingest.files import sniff_mime
from app.ingest.pdf import unlock_email
from app.trace.tracer import Tracer
from evals import outcomes
from evals.knockouts import Decision
from evals.runner import INBOXES, START, RunResult, StopRun, find_fixture, fresh_world, never
from evals.scenario import Scenario

MAX_STEPS = 20
THINKING = "medium"
SYSTEM = """You are an assistant that runs the accounts of a small Indian manufacturer.

You get the business's records and, in order, everything that happened: emails
that arrived, files that were uploaded, and what the owner did. Use the tools
to bring the records up to date, then give your final answer: the payment plan
for the coming weeks (the lowest balance, the day it falls on, and for every
bill PAY with a day, WAIT or ESCALATE) and a short summary.

Reply with JSON: notes, and exactly one of tool ({"name", "args"}) or final."""


class BareTool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class BareFinal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lowest_balance_text: str
    lowest_on: date | None = None
    decisions: list[Decision] = Field(default_factory=list)
    summary: str = ""


class BareStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = ""
    tool: BareTool | None = None
    final: BareFinal | None = None

    @model_validator(mode="after")
    def _one(self) -> BareStep:
        if (self.tool is None) == (self.final is None):
            raise ValueError("a step is exactly one tool call or a final answer")
        return self


@dataclass
class BareEnv:
    conn: Any
    clock: FakeClock
    emails: dict[str, bytes] = field(default_factory=dict)
    parts: list[Part] = field(default_factory=list)


# --- the tools: every one, write tools included, on the scratch database --------------------------


def _rows(env: BareEnv, sql: str, args: tuple = ()) -> str:
    rows = env.conn.execute(sql, args).fetchall()
    return "\n".join(", ".join(f"{k} {r[k]}" for k in r.keys()) for r in rows) or "none"


def _party(env: BareEnv, name: str) -> int:
    row = env.conn.execute("SELECT id FROM party WHERE business_id = 1 AND name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return env.conn.execute("INSERT INTO party (business_id, kind, name) VALUES (1, 'vendor', ?)", (name,)).lastrowid


def _record_transaction(env: BareEnv, a: dict) -> str:
    cur = env.conn.execute(
        "INSERT INTO bank_txn (account_id, direction, amount_paise, txn_date, counterparty, reference, dedup_key, "
        "status) VALUES (1, ?, ?, ?, ?, ?, ?, 'UNMATCHED')",
        (a["direction"], parse_inr(str(a["amount"])), a["date"], a.get("counterparty"), a.get("reference"),
         f"bare:{env.conn.execute('SELECT COUNT(*) FROM bank_txn').fetchone()[0]}:{a['date']}"))
    return f"transaction {cur.lastrowid} recorded"


def _add_bill(env: BareEnv, a: dict) -> str:
    cur = env.conn.execute(
        "INSERT INTO payable (business_id, party_id, invoice_number, amount_paise, due_date, priority, status) "
        "VALUES (1, ?, ?, ?, ?, ?, 'CONFIRMED')",
        (_party(env, a["party"]), a.get("invoice_number"), parse_inr(str(a["amount"])), a["due_date"],
         a.get("priority", "normal")))
    return f"bill {cur.lastrowid} added"


def _set(env: BareEnv, sql: str, args: tuple, what: str) -> str:
    return what if env.conn.execute(sql, args).rowcount else "no such record"


TOOLS: dict[str, Callable[[BareEnv, dict], str]] = {
    "list_bills": lambda env, a: _rows(env, "SELECT p.id, pt.name AS party, p.invoice_number, p.amount_paise, "
                                            "p.due_date, p.priority, p.status FROM payable p LEFT JOIN party pt "
                                            "ON pt.id = p.party_id ORDER BY p.id"),
    "list_receivables": lambda env, a: _rows(env, "SELECT r.id, pt.name AS party, r.amount_paise, r.expected_date, "
                                                  "r.confidence FROM receivable r LEFT JOIN party pt "
                                                  "ON pt.id = r.party_id ORDER BY r.id"),
    "list_transactions": lambda env, a: _rows(env, "SELECT id, direction, amount_paise, txn_date, counterparty, "
                                                   "status FROM bank_txn ORDER BY id"),
    "list_parties": lambda env, a: _rows(env, "SELECT id, name, bank_account_mask, bank_ifsc, bank_status FROM party"),
    "read_email": lambda env, a: email_text(email.message_from_bytes(env.emails[a["id"]], policy=email.policy.default))
    if a.get("id") in env.emails else "no such email",
    "read_attachment": lambda env, a: _read_attachment(env, a),
    "record_transaction": _record_transaction,
    "add_bill": _add_bill,
    "set_bill_status": lambda env, a: _set(env, "UPDATE payable SET status = ? WHERE id = ?",
                                           (a["status"], a["bill_id"]), "bill status set"),
    "set_bill_priority": lambda env, a: _set(env, "UPDATE payable SET priority = ? WHERE id = ?",
                                             (a["priority"], a["bill_id"]), "bill priority set"),
    "set_bill_due_date": lambda env, a: _set(env, "UPDATE payable SET due_date = ? WHERE id = ?",
                                             (a["due_date"], a["bill_id"]), "bill due date set"),
    "set_bank_details": lambda env, a: _set(
        env, "UPDATE party SET bank_account_mask = ?, bank_ifsc = ?, bank_status = 'verified' WHERE name = ?",
        ("XXXX" + str(a["account_number"]).replace(" ", "")[-4:], a.get("ifsc"), a["party"]), "bank details set"),
    "set_account_balance": lambda env, a: _set(env, "UPDATE bank_account SET reported_balance_paise = ? WHERE id = 1",
                                               (parse_inr(str(a["balance"])),), "balance set"),
}


def _read_attachment(env: BareEnv, a: dict) -> str:
    raw = env.emails.get(a.get("id"))
    if raw is None:
        return "no such email"
    opened = unlock_email(raw, str(a.get("password", ""))) if a.get("password") else raw
    if opened is None:
        return "the password did not open it"
    msg = email.message_from_bytes(opened, policy=email.policy.default)
    for att in msg.iter_attachments():
        data = att.get_payload(decode=True) or b""
        env.parts.append(Part(att.get_content_type(), data))
    return "its attachments are sent with your next step"


# --- the inputs, as text ----------------------------------------------------------------------------


def _state(env: BareEnv) -> str:
    b = env.conn.execute("SELECT * FROM business WHERE id = 1").fetchone()
    a = env.conn.execute("SELECT a.*, ab.calculated_balance_paise FROM bank_account a JOIN account_balance ab "
                         "ON ab.account_id = a.id WHERE a.id = 1").fetchone()
    lines = [f"Business: {b['name']}. Safety amount {format_inr(b['safety_amount_paise'])}; payment days "
             f"{b['payment_days']}; plan {b['horizon_days']} days ahead.",
             f"Account {a['account_mask']} at {a['bank_name']}: balance {format_inr(a['calculated_balance_paise'])}.",
             "Bills:", TOOLS["list_bills"](env, {}), "Expected receipts:", TOOLS["list_receivables"](env, {})]
    return "\n".join(lines)


def _events(env: BareEnv, scenario: Scenario) -> list[str]:
    out: list[str] = [f"It is {env.clock.now():%a %d %b %Y, %H:%M}."]
    for step in scenario.steps:
        ((kind, arg),) = step.items()
        if kind == "at":
            target = datetime.fromisoformat(arg).replace(tzinfo=TIMEZONE)
            env.clock.advance(max(target - env.clock.now(), timedelta(0)))
            out.append(f"It is now {target:%a %d %b %Y, %H:%M}.")
        elif kind == "deliver":
            for name in arg:
                raw = find_fixture(name, (scenario.folder, *INBOXES)).read_bytes()
                env.emails[name] = raw
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                atts = [att.get_filename() or att.get_content_type() for att in msg.iter_attachments()]
                out.append(f"Email arrived (id {name}):\n{email_text(msg)}"
                           + (f"\n[attachments: {', '.join(atts)}; read_attachment to open]" if atts else ""))
        elif kind == "upload":
            raw = find_fixture(arg["file"], (scenario.folder, FIXTURE_UPLOADS)).read_bytes()
            env.parts.append(Part(sniff_mime(raw, arg["kind"]) or "application/octet-stream", raw))
            out.append(f"The helper uploaded a {arg['kind']} ({arg['file']}); it is attached.")
        elif kind == "monday_plan":
            out.append("It is Monday morning: plan the payments.")
        elif kind == "approve":
            out.append("The owner approves the payments planned for today.")
        elif kind == "confirm_waiting":
            out.append("The owner confirms every new bill and transaction waiting for confirmation.")
        elif kind == "approve_bank_details":
            out.append("The owner has checked by phone and approves the vendor bank details waiting for approval.")
        elif kind == "unlock":
            out.append(f"The owner gives the statement PDF's password: {arg['password']}")
        elif kind == "confirm_balance":
            out.append(f"The owner says the account's real balance is Rs.{arg['amount']}.")
        elif kind == "choose_option":
            out.append({"early_receipt": "The owner asks Nandi Foods to pay their invoice early, by Fri 16 Oct."
                        }.get(arg, f"The owner chooses: {arg}."))
    return out


# --- one run --------------------------------------------------------------------------------------


def run_once(scenario: Scenario, backend: Backend, app_config: AppConfig, run: int = 1, *,
             should_stop: Callable[[], str | None] = never,
             inspect: Callable[[Any], dict[str, Any]] | None = None) -> RunResult:
    from evals import metrics

    with tempfile.TemporaryDirectory(prefix=f"bare-{scenario.name}-") as tmp_name:
        tmp = Path(tmp_name)
        clock = FakeClock(START)
        conn = fresh_world(tmp / "bare.db", clock)
        env = BareEnv(conn, clock)
        tracer = Tracer(f"bare-{scenario.name}-{run}", str(tmp / "traces"), clock)
        history = [_state(env), "What happened, in order:", *_events(env, scenario)]
        result = RunResult(scenario.name, run, "PASSED")
        final: BareFinal | None = None
        try:
            for i in range(1, MAX_STEPS + 1):
                reason = should_stop()
                if reason:
                    raise StopRun(reason)
                r = call(job="bare", thinking=THINKING, system=SYSTEM, context=["\n\n".join(history), *env.parts],
                         schema=BareStep, backend=backend, app_config=app_config, tracer=tracer,
                         input_ref=f"bare:{scenario.name}")
                if r.parsed is None:
                    history.append(f"Step {i}: your reply did not match the format ({r.schema_error}).")
                    continue
                if r.parsed.final is not None:
                    final = r.parsed.final
                    break
                tool = r.parsed.tool
                try:
                    out = TOOLS[tool.name](env, tool.args) if tool.name in TOOLS else f"no tool {tool.name!r}"
                except (KeyError, ValueError, TypeError) as e:
                    out = f"error: {type(e).__name__}: {e}"
                conn.commit()
                tracer.step(input_ref=f"bare:{scenario.name}", tool=f"agent:{tool.name}", arguments=tool.args,
                            result=out[:2000])
                history.append(f"Step {i}: {r.text}\nResult: {out}")
        except StopRun as e:
            result.status, result.error = "ERRORED", str(e)
        except AIUnavailable as e:
            result.status, result.error = "ERRORED", f"AI unavailable: {e}"
        if result.status != "ERRORED":
            plan = None
            if final is not None:
                try:
                    lowest = parse_inr(final.lowest_balance_text)
                except ValueError:
                    lowest = None
                plan = {"lowest_paise": lowest, "lowest_on": final.lowest_on.isoformat() if final.lowest_on else None,
                        "decisions": {d.bill_id: f"{d.decision} {d.pay_on.isoformat()}" if d.decision == "PAY"
                                      and d.pay_on else d.decision for d in final.decisions}}
            result.outcomes = outcomes.score(conn, scenario.outcome, plan)
            if not result.outcome_ok:
                result.status = "FAILED"
            if final is None:
                result.error = f"no final answer in {MAX_STEPS} steps"
        result.metrics = metrics.collect(metrics.trace_steps(tmp / "traces"), conn)
        conn.close()
        shutil.rmtree(tmp / "traces", ignore_errors=True)
    return result
