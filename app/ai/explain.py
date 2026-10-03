"""Explaining a replan (TDD Part 2, "Explaining a change"; batch 6, CHG-018):
one Gemini call at the configured (low) thinking level, from the plan diff
written out as text by code. The reply is only words for the owner; code
checks every amount and date in it (app/validate/summary.py) before it is
shown, and builds a template instead when the check fails."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.ai.client import AIResult, Backend, call, load_prompt
from app.config import AppConfig
from app.trace.tracer import Tracer

EXPLAIN_PROMPT = "explain_plan.v1"


class PlanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str


def explain_changes(changes_text: str, *, backend: Backend, app_config: AppConfig, tracer: Tracer,
                    input_ref: str) -> AIResult:
    return call(
        job="explain", thinking=app_config.model.thinking.explain, system=load_prompt(EXPLAIN_PROMPT),
        context=changes_text, schema=PlanSummary, backend=backend, app_config=app_config, tracer=tracer,
        input_ref=input_ref, prompt_version=f"{app_config.prompts.version}/{EXPLAIN_PROMPT}",
    )
