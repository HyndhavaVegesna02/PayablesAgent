"""One step of the exception agent (TDD Part 2, "Agent loop"; batch 6,
CHG-008, S2): one Gemini call with the case file, never a chat history. The
reply is an AgentStep, parsed by code: notes plus exactly one tool call or a
final answer. A final answer has no action field, so there is nothing in it
code could be asked to do; what it may lead to is decided by code
(app/jobs/run_case.py, apply_final)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.client import AIResult, Backend, call, load_prompt
from app.config import AppConfig
from app.trace.tracer import Tracer

AGENT_PROMPT = "exception_agent.v1"


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["RESOLVED", "NEEDS_OWNER"]
    summary: str = Field(max_length=600)  # shown to the owner as plain text
    cited_message_ids: list[str] = Field(default_factory=list)
    relied_on_candidate_ids: list[int] = Field(default_factory=list)


class AgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str
    tool: ToolCall | None = None
    final: FinalAnswer | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> AgentStep:
        if (self.tool is None) == (self.final is None):
            raise ValueError("a step is exactly one tool call or a final answer")
        return self


def next_step(case_file_md: str, *, thinking: str, backend: Backend, app_config: AppConfig, tracer: Tracer,
              input_ref: str) -> AIResult:
    return call(
        job="exception", thinking=thinking, system=load_prompt(AGENT_PROMPT), context=case_file_md,
        schema=AgentStep, backend=backend, app_config=app_config, tracer=tracer, input_ref=input_ref,
        prompt_version=f"{app_config.prompts.version}/{AGENT_PROMPT}",
    )
