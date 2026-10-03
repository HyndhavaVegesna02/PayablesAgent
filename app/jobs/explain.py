"""The explain_plan job (TDD Part 2, "Jobs" and "Explaining a change"; batch
6, CHG-018). A replan queues it with the new run and the run it replaced.
Code diffs the two stored runs and writes the changes as plain sentences;
Gemini may turn them into a short note, which is kept only if every amount
and date in it is one the diff holds (app/validate/summary.py). Otherwise,
and when there is no AI or it fails, the note is those sentences: the
template. A replan that changed nothing gets no note and no AI call."""

from __future__ import annotations

import functools
import sqlite3
from typing import TYPE_CHECKING, Any

from app.ai.client import AIUnavailable, Backend
from app.ai.explain import explain_changes
from app.config import AppConfig
from app.db.read import bill_names, persisted_result
from app.domain.money import format_inr
from app.jobs.queue import PermanentJobError
from app.planner.diff import PlanDiff, diff
from app.planner.plan import format_day
from app.trace.tracer import Tracer
from app.validate import PASSED
from app.validate.summary import check_summary

if TYPE_CHECKING:
    from app.worker import Handler, JobContext

MAX_TEMPLATE_LINES = 6


def _decision(side: dict[str, Any]) -> str:
    return f"{side['decision']} on {format_day(side['pay_on'])}" if side.get("pay_on") else side["decision"]


def change_lines(d: PlanDiff, names: dict[int, str]) -> list[str]:
    """One sentence per change, every figure formatted from the diff."""
    out = []
    for c in d.changes:
        b, a = c.before or {}, c.after or {}
        name = names.get(c.payable_id, "A bill") if c.payable_id is not None else ""
        if c.kind == "opening_cash":
            out.append(f"Cash at the start now {format_inr(a['amount_paise'])} (was {format_inr(b['amount_paise'])}).")
        elif c.kind == "lowest":
            out.append(f"Lowest balance now {format_inr(a['amount_paise'])} on {format_day(a['on'])} "
                       f"(was {format_inr(b['amount_paise'])} on {format_day(b['on'])}).")
        elif c.kind == "validity":
            out.append("The plan now stays above the safety amount." if a["valid"]
                       else "The plan now goes below the safety amount.")
        elif c.kind == "line_added":
            out.append(f"{name} {format_inr(a['amount_paise'])}: {_decision(a)} (new in the plan).")
        elif c.kind == "line_removed":
            out.append(f"{name}: no longer in the plan (was {_decision(b)}).")
        else:
            amount = (f" now {format_inr(a['amount_paise'])} (was {format_inr(b['amount_paise'])})"
                      if a["amount_paise"] != b["amount_paise"] else "")
            out.append(f"{name}{amount}: {_decision(a)} (was {_decision(b)}).")
    return out


def template_summary(lines: list[str]) -> str:
    shown = lines[:MAX_TEMPLATE_LINES]
    if len(lines) > len(shown):
        shown.append("Other bills changed too; see the plan below.")
    return " ".join(shown)


def explain_plan(conn: sqlite3.Connection, run_id: int, previous_run_id: int, *, backend: Backend | None,
                 app_config: AppConfig, tracer: Tracer) -> str | None:
    """Stores the run's summary and its source; returns the source, or None
    when the plan did not change."""
    input_ref = f"plan_run:{run_id}"
    d = diff(persisted_result(conn, previous_run_id), persisted_result(conn, run_id))
    if not d.changes:
        tracer.step(input_ref=input_ref, tool="explain_plan", result=f"no changes since plan_run {previous_run_id}")
        return None
    (business_id,) = conn.execute("SELECT business_id FROM plan_run WHERE id = ?", (run_id,)).fetchone()
    lines = change_lines(d, bill_names(conn, business_id))
    text, source = None, "template"
    if backend is not None:
        try:
            r = explain_changes("\n".join(lines), backend=backend, app_config=app_config, tracer=tracer,
                                input_ref=input_ref)
        except AIUnavailable as e:
            tracer.step(input_ref=input_ref, tool="explain_plan", result=f"template: AI unavailable ({e})")
        else:
            if r.parsed is None:
                verdict = f"failed: the reply did not match the schema ({r.schema_error})"
            else:
                summary = " ".join(r.parsed.summary.split())  # one plain paragraph
                verdict = check_summary(summary, d.amounts_paise, d.dates)
            tracer.step(input_ref=input_ref, tool="check_summary", validation=verdict)
            if verdict == PASSED:
                text, source = summary, "gemini"
    if text is None:
        text = template_summary(lines)
    conn.execute("UPDATE plan_run SET summary_text = ?, summary_source = ? WHERE id = ?", (text, source, run_id))
    tracer.step(input_ref=input_ref, tool="explain_plan", result=f"summary from {source}")
    return source


def handle_explain_plan(ctx: JobContext, *, backend: Backend | None) -> None:
    run_id, previous = ctx.payload.get("plan_run_id"), ctx.payload.get("previous_run_id")
    if type(run_id) is not int or type(previous) is not int:
        raise PermanentJobError(f"explain_plan needs int plan_run_id and previous_run_id, got {ctx.payload!r}")
    try:
        explain_plan(ctx.conn, run_id, previous, backend=backend, app_config=ctx.app_config, tracer=ctx.tracer)
    except LookupError as e:
        raise PermanentJobError(str(e)) from None


def handlers(backend: Backend | None) -> dict[str, Handler]:
    """Registered with or without an AI backend: without one, every note is the template."""
    return {"explain_plan": functools.partial(handle_explain_plan, backend=backend)}
