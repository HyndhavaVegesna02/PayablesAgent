"""Step 3 of the document pipeline: extract one record with Gemini, using a
JSON schema generated from these models (TDD Part 2, "The pipeline for one
document"). The models hold text exactly as written; code turns amounts into
paise (app.domain.money.parse_inr) and checks every field, so the model never
produces a number the ledger stores (batch 2 plan, Q4)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.client import AIResult, Backend, call, load_prompt
from app.config import AppConfig
from app.trace.tracer import Tracer


class BankAlertExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_last4: str = Field(pattern=r"^[0-9]{4}$")
    direction: Literal["debit", "credit"]
    amount_text: str
    txn_date: date
    counterparty: str | None
    reference: str | None
    available_balance_text: str | None
    uncertain_fields: list[str]


class FailureNoticeExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_last4: str = Field(pattern=r"^[0-9]{4}$")
    amount_text: str
    original_reference: str | None
    failure_date: date
    reason: str
    uncertain_fields: list[str]


EXTRACTORS: dict[str, tuple[str, type[BaseModel]]] = {
    "bank_alert": ("extract_bank_alert.v1", BankAlertExtract),
    "failure_notice": ("extract_failure.v1", FailureNoticeExtract),
}


def prompt_version(app_config: AppConfig, doc_type: str) -> str:
    return f"{app_config.prompts.version}/{EXTRACTORS[doc_type][0]}"


def retry_context(text: str, previous: str | None, failed_checks: dict[str, str]) -> str:
    """The document again, with the last answer and the checks it failed, so
    the next attempt can correct itself (pipeline step 4)."""
    failures = "\n".join(f"- {name}: {why}" for name, why in sorted(failed_checks.items()))
    return (
        f"{text}\n\n---\nA previous reading of this email failed these checks:\n{failures}\n"
        f"The previous answer was:\n{previous if previous is not None else '(no answer)'}\n"
        "Read the email again and return corrected JSON."
    )


def extract_document(
    doc_type: str,
    text: str,
    *,
    thinking: str,
    backend: Backend,
    app_config: AppConfig,
    tracer: Tracer,
    input_ref: str,
    previous: str | None = None,
    failed_checks: dict[str, str] | None = None,
) -> AIResult:
    prompt, schema = EXTRACTORS[doc_type]
    context = text if not failed_checks else retry_context(text, previous, failed_checks)
    return call(
        job=f"extract:{doc_type}", thinking=thinking, system=load_prompt(prompt), context=context,
        schema=schema, backend=backend, app_config=app_config, tracer=tracer, input_ref=input_ref,
        prompt_version=prompt_version(app_config, doc_type),
    )
