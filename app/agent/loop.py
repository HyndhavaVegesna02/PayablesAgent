"""run_case (TDD Part 2, "Agent loop"; batch 6, CHG-008, S5). Each step is one
Gemini call with the case file, never a growing chat history. Code opens the
case, checks every tool call (allow-list, args model, loop detection), counts
the limits, and saves the case after every step in its own commit, so a run
that stops (a crash, an outage) resumes at the step it reached.

The loop returns the final answer, if the agent gave one; applying it is
code's job outside this package (app/jobs/run_case.py), so nothing here can
change the ledger."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.agent import cases, escalation
from app.agent.case_file import finding
from app.agent.cases import Case
from app.agent.tools import TOOLS, ToolContext, open_question
from app.ai.agent_step import FinalAnswer, next_step
from app.ai.client import Backend
from app.clock import Clock
from app.config import AppConfig
from app.ingest.mail_source import MailSource
from app.ingest.store import DocumentStore
from app.trace.tracer import Tracer

FALLBACK_QUESTION = ("The assistant could not settle this case within its limits. Please look at it: "
                     "{goal}")


@dataclass
class Outcome:
    case: Case
    final: FinalAnswer | None  # the agent's answer; None when the run ended at the owner


@dataclass
class Deps:
    backend: Backend
    app_config: AppConfig
    tracer: Tracer
    mail: MailSource
    clock: Clock
    db_path: str
    store: DocumentStore | None = None
    # Hands a case that ends without an answer to the owner. The default asks an
    # agent_question; the run_case job passes one that, for a drift case, asks
    # confirm_balance instead (TDD "Drift check", step 5), which needs the writer.
    to_owner: Callable[[sqlite3.Connection, Case, str], None] | None = None


def _cut(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def ask_agent_question(conn: sqlite3.Connection, case: Case, question: str, d: Deps) -> None:
    open_question(ToolContext(conn, d.db_path, case, d.mail, d.clock, case.state.get("steps_total", 0), d.store),
                  _cut(question), [])
    case.status = "ASK_OWNER"


def _canonical(name: str, args: dict) -> str:
    return json.dumps({"name": name, "args": args}, sort_keys=True, default=str)


def _save(conn: sqlite3.Connection, case: Case, clock: Clock) -> None:
    cases.save(conn, case, clock)
    conn.commit()  # one step, one commit: the resume point


def _tool_step(conn: sqlite3.Connection, case: Case, d: Deps, name: str, args: dict) -> None:
    """Runs one tool call, or refuses it with a note. Every outcome is a step."""
    step = case.state.get("steps_total", 0)
    spec = TOOLS.get(name)
    if spec is None:
        case.add_note(f"step {step}: refused unknown tool {name!r}; the tools are {', '.join(TOOLS)}")
        d.tracer.step(input_ref=f"agent_case:{case.id}", tool=f"agent:{name}", result="refused: unknown tool")
        return
    call = _canonical(name, args)
    if case.state.get("last_call") == call:
        case.add_note(f"step {step}: refused {name}: the same call as the step before")
        d.tracer.step(input_ref=f"agent_case:{case.id}", tool=f"agent:{name}", arguments=args,
                      result="refused: repeated call")
        return
    case.state["last_call"] = call
    try:
        parsed = spec.args_model.model_validate(args)
    except ValidationError as e:
        problem = f"{e.errors()[0].get('loc')}: {e.errors()[0].get('msg')}"
        case.add_note(f"step {step}: refused {name}: {problem}")
        d.tracer.step(input_ref=f"agent_case:{case.id}", tool=f"agent:{name}", arguments=args,
                      result=f"refused: {problem}")
        return
    ctx = ToolContext(conn, d.db_path, case, d.mail, d.clock, step, d.store)
    try:
        result = spec.run(ctx, parsed)
    except Exception as e:  # noqa: BLE001 - a source error is a step the agent reads, not a crash
        problem = f"{type(e).__name__}: {e}"[:200]
        case.add_note(f"step {step}: {name} failed: {problem}")
        d.tracer.step(input_ref=f"agent_case:{case.id}", tool=f"agent:{name}", arguments=args,
                      result=f"error: {problem}")
        return
    args_text = ", ".join(f"{k}={v!r}" for k, v in parsed.model_dump(mode="json").items())
    case.state.setdefault("findings", []).append(finding(step, name, args_text, result))
    d.tracer.step(input_ref=f"agent_case:{case.id}", tool=f"agent:{name}", arguments=args, result=result)


def run_case(conn: sqlite3.Connection, case_id: int, d: Deps) -> Outcome:
    case = cases.load(conn, case_id)
    if case.status != "OPEN":
        d.tracer.step(input_ref=f"agent_case:{case_id}", tool="run_case", result=f"case is {case.status}")
        return Outcome(case, None)
    limits = d.app_config.escalation
    if "steps_total" not in case.state:  # the first run: the opening rule, as code decided it
        threshold = conn.execute("SELECT escalation_stake_paise FROM business WHERE id = ?",
                                 (case.business_id,)).fetchone()[0]
        thinking, rule = escalation.start_thinking(case.stake_paise, threshold)
        case.thinking, case.escalation_rule = thinking, rule
        case.state["steps_total"] = 0
        d.tracer.step(input_ref=f"agent_case:{case.id}", tool="escalation", escalation_rule=rule,
                      result=f"starts at {thinking}")
    while True:
        while escalation.run_over(case.steps, case.validation_failures, max_steps=limits.max_steps,
                                  max_failures=limits.max_validation_failures) is None:
            r = next_step(case.case_file_md, thinking=case.thinking, backend=d.backend, app_config=d.app_config,
                          tracer=d.tracer, input_ref=f"agent_case:{case.id}")
            case.steps += 1
            case.state["steps_total"] = case.state.get("steps_total", 0) + 1
            step = r.parsed
            if step is None:
                case.add_note(f"step {case.state['steps_total']}: the reply did not match the step schema "
                              f"({r.schema_error})")
            else:
                case.add_note(f"step {case.state['steps_total']}: {step.notes}")
                if step.final is not None:
                    _save(conn, case, d.clock)
                    return Outcome(case, step.final)
                _tool_step(conn, case, d, step.tool.name, step.tool.args)
            _save(conn, case, d.clock)
            if case.status == "ASK_OWNER":  # ask_owner ends the run
                return Outcome(case, None)
        rule = escalation.run_over(case.steps, case.validation_failures, max_steps=limits.max_steps,
                                   max_failures=limits.max_validation_failures)
        case.escalation_rule = rule
        d.tracer.step(input_ref=f"agent_case:{case.id}", tool="escalation", escalation_rule=rule,
                      result=f"run over at {case.thinking}: {escalation.after_run(case.thinking)}")
        if escalation.after_run(case.thinking) == "rerun_high":
            case.thinking, case.steps, case.validation_failures = "high", 0, 0
            case.state.pop("last_call", None)  # loop detection is per run
            case.add_note(f"the medium run ended ({rule}); rerunning at high thinking")
            _save(conn, case, d.clock)
            continue
        question = FALLBACK_QUESTION.format(goal=case.state.get("goal", ""))
        if d.to_owner is None:
            ask_agent_question(conn, case, question, d)
        else:
            d.to_owner(conn, case, question)
        case.add_note(f"the high run ended ({rule}); the owner is asked")
        _save(conn, case, d.clock)
        return Outcome(case, None)
