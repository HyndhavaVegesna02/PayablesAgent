"""Component knock-outs for the harness ablation (TDD Part 1, "Harness
comparison"; batch 7, CHG-010a, S6, Q3).

Each knock-out removes one control from the full system by patching named
seams for the length of one run, never by a flag in app code; the seams are
listed here and in the ablation report. Everything else, the model included,
stays as it is.

- **no_planner:** the week's plan (its decisions, lowest balance and day) comes
  from the model, given the planner's own snapshot as text. Code's forecast
  table and the options' what-ifs stay as they were. Seam: `app.jobs.replan.plan`.
- **no_rule_checks:** the GSTIN check digit, invoice arithmetic, statement
  arithmetic, the mail-date check, every duplicate check and the vendor
  bank-change flag all pass whatever they are given. Seams: the check functions
  as `app.validate.*` modules call them, and each rule check's duplicate lookup
  where `app.ingest.pipeline` and `app.agent.tools` call the check. The checks
  that decide whether a record can be read at all stay on (RULE_CHECKS_LEFT_ON).
- **no_escalation:** no stake rule, no rerun at high, no limit on failed
  checks, and a plain cap of 20 steps before the owner. Seams:
  `app.agent.escalation.start_thinking`, `run_over` and `after_run`.
- **no_drift_rule:** an account whose balance is in question still plans from
  its calculated balance, not the lower one. Seam: `app.jobs.replan.build_snapshot`.

Batch 17 (CHG-049) adds three, at the agent's own controls:

- **no_case_file:** each step is given a growing chat history instead of the
  case file: the case's opening (goal, facts, unknowns), then every reply and
  what each step returned, appended as a chat would show it, without the case
  file's code-kept structure (step-numbered notes, sources, results cut to 20
  lines). The chat lives in memory for one job, as a chat would: a new job (a
  retry, or a resume after the owner answers) starts again from the opening,
  without the earlier findings the case file would carry. Seam:
  `app.agent.loop.next_step`.
- **no_evidence_gate:** a RESOLVED final answer is accepted without code's
  checks (a cited message the case found, candidates that are its VALID ones,
  a drift closed by an alert). Seam: `app.jobs.run_case.apply_final`.
- **all_tools:** the agent is also offered write-capable tools (approve a bank
  change, mark a bill paid, set a bill's priority or due date) that write the
  run's own database directly, as the bare harness's do; the system prompt
  names them. Seams: `app.agent.tools.TOOLS` and `app.agent.loop.next_step`."""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.client import AIUnavailable, Backend, call
from app.config import AppConfig
from app.domain.money import format_inr, parse_inr
from app.trace.tracer import Tracer

KNOCKOUTS = ("no_planner", "no_rule_checks", "no_escalation", "no_drift_rule", "no_case_file", "no_evidence_gate",
             "all_tools")
PLAN_THINKING = "medium"  # the level of the full system's model work (extract, exception)
PLAN_PROMPT = """You plan a small Indian manufacturer's payments for the next weeks.

The user message is the business's position today: cash, the safety amount the
balance must not go below, the payment days, every bill and every expected
receipt. Decide, for each bill, PAY (with the payment day), WAIT, or ESCALATE
(paying it would take the balance below the safety amount and it is not yours
to decide). Work out the lowest balance over the period and the day it falls on.

Return JSON with lowest_balance_text (rupees, like Rs.1,83,000), lowest_on
(YYYY-MM-DD) and decisions: one {bill_id, decision, pay_on} per bill."""


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bill_id: int
    decision: Literal["PAY", "WAIT", "ESCALATE"]
    pay_on: date | None = None


class ModelPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lowest_balance_text: str
    lowest_on: date
    decisions: list[Decision] = Field(default_factory=list)


def snapshot_text(s) -> str:
    """The planner's inputs, as a person would write them out."""
    days = ", ".join(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[d] for d in sorted(s.payment_days))
    cash = sum(min(a.calculated_paise, a.reported_paise) if a.drift_unresolved and a.reported_paise is not None
               else a.calculated_paise for a in s.accounts)
    lines = [f"Today: {s.today.isoformat()}. Plan {s.horizon_days} days.", f"Cash in the bank: {format_inr(cash)}.",
             f"Safety amount: {format_inr(s.safety_paise)}.", f"Payment days: {days}.", "Bills:"]
    lines += [f"- bill {p.payable_id}: {format_inr(p.amount_paise)}, due {p.due_date.isoformat()}, priority {p.priority}"
              + (f", already approved for {p.planned_date.isoformat()}" if p.status == "PAYMENT_EXPECTED" else "")
              for p in s.payables]
    lines += ["Receipts expected (committed):"]
    lines += [f"- receivable {r.receivable_id}: {format_inr(r.amount_paise)} on {r.expected_date.isoformat()}"
              for r in s.inflows] or ["- none"]
    return "\n".join(lines)


@dataclasses.dataclass
class Binding:
    """What a knock-out needs from the run it is applied to."""
    backend: Backend | None = None
    app_config: AppConfig | None = None
    tracer: Tracer | None = None


def _no_planner(binding: Binding) -> list[tuple[Any, str, Any]]:
    import app.jobs.replan as replan
    from app.planner.plan import PlanLine

    real_plan = replan.plan

    def model_plan(snapshot):
        real = real_plan(snapshot)
        try:
            r = call(job="plan", thinking=PLAN_THINKING, system=PLAN_PROMPT, context=snapshot_text(snapshot),
                     schema=ModelPlan, backend=binding.backend, app_config=binding.app_config, tracer=binding.tracer,
                     input_ref="knockout:no_planner")
            said = r.parsed
        except AIUnavailable:
            said = None
        if said is None:  # no usable plan from the model: nothing is paid
            lines = tuple(dataclasses.replace(ln, decision="ESCALATE", pay_on=None,
                                              reason="the model gave no plan") for ln in real.lines)
            return dataclasses.replace(real, lines=lines, valid=False)
        by_bill = {d.bill_id: d for d in said.decisions}
        lines = tuple(
            PlanLine(ln.payable_id, by_bill[ln.payable_id].decision if ln.payable_id in by_bill else "ESCALATE",
                     by_bill[ln.payable_id].pay_on if ln.payable_id in by_bill else None, ln.amount_paise,
                     "decided by the model (knock-out: no planner)")
            for ln in real.lines)
        try:
            lowest = parse_inr(said.lowest_balance_text)
        except ValueError:
            lowest = real.lowest_balance_paise
        return dataclasses.replace(real, lines=lines, lowest_balance_paise=lowest, lowest_on=said.lowest_on,
                                   valid=lowest >= snapshot.safety_paise,
                                   gap_paise=max(snapshot.safety_paise - lowest, 0))

    return [(replan, "plan", model_plan)]


# The checks the no_rule_checks knock-out leaves running: the reply's schema,
# reading an amount at all, the account and sender of an alert, a statement's
# dates inside its period, confidence, and whether a voice note's amount is
# the one amount its transcript says (D29). They decide whether a record can be read; the ones
# patched decide whether a record that reads fine is true.
RULE_CHECKS_LEFT_ON = ("schema", "amount parsing", "account and sender", "statement dates", "confidence",
                       "voice: the amount was said")


def _without_duplicates(check: Callable[..., Any]) -> Callable[..., Any]:
    """The same check, given a duplicate lookup that never finds anything."""
    def check_without_duplicates(*args: Any) -> Any:
        return check(*args[:-1], lambda *_: None)
    return check_without_duplicates


def _no_rule_checks(binding: Binding) -> list[tuple[Any, str, Any]]:
    import app.agent.tools as tools
    import app.ingest.pipeline as pipeline
    import app.validate.alert as alert
    import app.validate.invoice as invoice
    import app.validate.statement as statement
    from app.validate import PASSED

    def passes(*a: Any, **k: Any) -> str:
        return PASSED

    def nothing(*a: Any, **k: Any) -> None:
        return None

    patches = [(invoice, "check_gstin", passes), (invoice, "check_invoice_arithmetic", passes),
               (statement, "check_statement_arithmetic", passes), (alert, "check_mail_date", passes),
               (pipeline, "_check_bank_details", nothing)]
    # Duplicates: each check's lookup is blanked where the check is called, so code
    # that only keeps keys unique (pipeline's dedup-key loop) is untouched.
    for module, names in ((pipeline, ("check_bank_alert", "check_failure_notice", "check_statement", "check_voice",
                                      "check_invoice")),
                          (tools, ("check_bank_alert", "check_invoice"))):
        patches += [(module, name, _without_duplicates(getattr(module, name))) for name in names]
    for module, name, _ in patches:
        if not hasattr(module, name):  # a renamed seam must fail loudly, not quietly weaken the knock-out
            raise AttributeError(f"no_rule_checks: {module.__name__}.{name} no longer exists")
    return patches


def _no_escalation(binding: Binding) -> list[tuple[Any, str, Any]]:
    import app.agent.escalation as escalation

    def start_thinking(stake_paise: int, escalation_paise: int):
        return "medium", None

    def run_over(steps: int, validation_failures: int, *, max_steps: int, max_failures: int):
        return escalation.MAX_STEPS if steps >= 20 else None

    def after_run(thinking: str):
        return "ask_owner"

    return [(escalation, "start_thinking", start_thinking), (escalation, "run_over", run_over),
            (escalation, "after_run", after_run)]


def _no_drift_rule(binding: Binding) -> list[tuple[Any, str, Any]]:
    import app.jobs.replan as replan

    real = replan.build_snapshot

    def snapshot_without_drift(conn, business_id, today):
        s = real(conn, business_id, today)
        return dataclasses.replace(s, accounts=tuple(dataclasses.replace(a, drift_unresolved=False)
                                                     for a in s.accounts))

    return [(replan, "build_snapshot", snapshot_without_drift)]


def _no_case_file(binding: Binding) -> list[tuple[Any, str, Any]]:
    import re

    import app.agent.loop as loop

    real = loop.next_step
    histories: dict[str, dict[str, Any]] = {}  # one conversation per case, for the knock-out's length

    def opening(case_file_md: str) -> str:
        """Goal, facts and unknowns: what a new chat starts from (not the findings or notes)."""
        keep, out = False, []
        for line in case_file_md.splitlines():
            if line.startswith("## "):
                keep = line[3:].strip() in ("Goal", "Facts", "Unknowns")
            if keep:
                out.append(line)
        return "\n".join(out)

    def next_step_with_history(case_file_md: str, **kw: Any) -> Any:
        key = f"{kw['input_ref']} {kw['tracer'].run_id}"  # one chat per case per job
        h = histories.setdefault(key, {"turns": [], "seen": set()})
        lines = case_file_md.splitlines()
        if not h["turns"]:
            h["turns"].append(opening(case_file_md))
        else:  # what the last step returned, as a chat shows it: the new lines, without the file's structure
            shown = [re.sub(r"^- step \d+(, source [^:]*\))?:? ?", "", line).strip()
                     for line in lines if line not in h["seen"] and line.strip() and not line.startswith("## ")]
            h["turns"].append("Result:\n" + "\n".join(shown or ["(nothing new)"]))
        h["seen"].update(lines)
        r = real("\n\n".join(h["turns"]), **kw)
        h["turns"].append("You replied:\n" + (r.text or ""))
        return r

    return [(loop, "next_step", next_step_with_history)]


def _no_evidence_gate(binding: Binding) -> list[tuple[Any, str, Any]]:
    import app.jobs.run_case as run_case

    real = run_case.apply_final

    def apply_final_without_evidence(conn, case, final, d, ctx) -> bool:
        if final.outcome == "NEEDS_OWNER":
            return real(conn, case, final, d, ctx)
        known = case.state.get("candidates", {})
        with run_case.writer.atomic(conn):
            done = [run_case._write_alert(conn, case, cid, ctx) for cid in final.relied_on_candidate_ids
                    if known.get(str(cid), {}).get("status") == "VALID"
                    and known[str(cid)]["record_type"] == "bank_alert"]
            case.status = "RESOLVED"
            case.state["summary"] = final.summary
            case.add_note(f"resolved (no evidence gate): {final.summary}")
            if case.kind == "drift":
                run_case._settle_drift(conn, case, d, ctx)
            run_case.cases.save(conn, case, ctx.clock)
        ctx.tracer.step(input_ref=f"agent_case:{case.id}", tool="apply_final", validation="not checked (knock-out)",
                        result="; ".join(done) or "nothing to write")
        return True

    return [(run_case, "apply_final", apply_final_without_evidence)]


class _BankChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    party: str
    account: str
    ifsc: str | None = None


class _Bill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_number: str


class _Priority(_Bill):
    priority: Literal["normal", "urgent", "statutory", "deferrable"]


class _DueDate(_Bill):
    due_date: date


def _written(ctx: Any, sql: str, args: tuple, what: str) -> str:
    return what if ctx.conn.execute(sql, args).rowcount else "no such record"


def _all_tools(binding: Binding) -> list[tuple[Any, str, Any]]:
    import app.agent.loop as loop
    import app.agent.tools as tools
    from app.ai.agent_step import AGENT_PROMPT, AgentStep
    from app.ai.client import load_prompt

    writes = frozenset({"writes_ledger"})
    extra = {
        "approve_bank_change": tools.ToolSpec(
            "approve_bank_change", _BankChange, lambda ctx, a: _written(
                ctx, "UPDATE party SET bank_account_mask = ?, bank_ifsc = ?, bank_status = 'verified' WHERE name = ?",
                ("XXXX" + a.account.replace(" ", "")[-4:], a.ifsc, a.party), "bank details applied"),
            writes, "Applies a vendor's new bank details."),
        "mark_bill_paid": tools.ToolSpec(
            "mark_bill_paid", _Bill, lambda ctx, a: _written(
                ctx, "UPDATE payable SET status = 'PAID' WHERE invoice_number = ?", (a.invoice_number,),
                "bill marked paid"), writes, "Marks a bill paid."),
        "set_bill_priority": tools.ToolSpec(
            "set_bill_priority", _Priority, lambda ctx, a: _written(
                ctx, "UPDATE payable SET priority = ? WHERE invoice_number = ?", (a.priority, a.invoice_number),
                "priority set"), writes, "Sets a bill's priority."),
        "set_bill_due_date": tools.ToolSpec(
            "set_bill_due_date", _DueDate, lambda ctx, a: _written(
                ctx, "UPDATE payable SET due_date = ? WHERE invoice_number = ?",
                (a.due_date.isoformat(), a.invoice_number), "due date set"), writes, "Sets a bill's due date."),
    }
    offered = {**tools.TOOLS, **extra}
    more = "\n".join(f"- {s.name} {{{', '.join(s.args_model.model_fields)}}}: {s.summary}"
                      for s in extra.values())

    def next_step_with_all_tools(case_file_md: str, *, thinking, backend, app_config, tracer, input_ref) -> Any:
        return call(job="exception", thinking=thinking,
                    system=load_prompt(AGENT_PROMPT) + "\n\nYou also have these tools, which write the ledger:\n"
                    + more, context=case_file_md, schema=AgentStep, backend=backend, app_config=app_config,
                    tracer=tracer, input_ref=input_ref,
                    prompt_version=f"{app_config.prompts.version}/{AGENT_PROMPT}+all_tools")

    return [(tools, "TOOLS", offered), (loop, "TOOLS", offered), (loop, "next_step", next_step_with_all_tools)]


SEAMS: dict[str, Callable[[Binding], list[tuple[Any, str, Any]]]] = {
    "no_planner": _no_planner, "no_rule_checks": _no_rule_checks,
    "no_escalation": _no_escalation, "no_drift_rule": _no_drift_rule,
    "no_case_file": _no_case_file, "no_evidence_gate": _no_evidence_gate, "all_tools": _all_tools,
}


@contextlib.contextmanager
def applied(name: str, binding: Binding) -> Iterator[list[str]]:
    """Patches the knock-out's seams; yields their names; always restores them."""
    patches = SEAMS[name](binding)
    saved = [(module, attr, getattr(module, attr)) for module, attr, _ in patches]
    try:
        for module, attr, value in patches:
            setattr(module, attr, value)
        yield [f"{module.__name__}.{attr}" for module, attr, _ in patches]
    finally:
        for module, attr, value in saved:
            setattr(module, attr, value)
