"""Step 1 of the document pipeline: sort one document with Gemini at the
configured (low) thinking level (TDD Part 2, "The pipeline for one document")."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.ai.client import AIResult, Backend, Contents, call, load_prompt
from app.config import AppConfig
from app.trace.tracer import Tracer

SORT_PROMPT = "sort.v2"  # v2: uploads and attachments too (batch 5, S3)
DocType = Literal[
    "bank_alert", "failure_notice", "statement", "invoice", "challan", "payment_confirmation",
    "irrelevant",
]


class SortResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: DocType
    reason: str


def sort_document(text: Contents, *, backend: Backend, app_config: AppConfig, tracer: Tracer,
                  input_ref: str) -> AIResult:
    return call(
        job="sort", thinking=app_config.model.thinking.sort, system=load_prompt(SORT_PROMPT),
        context=text, schema=SortResult, backend=backend, app_config=app_config, tracer=tracer,
        input_ref=input_ref, prompt_version=f"{app_config.prompts.version}/{SORT_PROMPT}",
    )
