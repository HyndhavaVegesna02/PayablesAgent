"""Step 3 of the document pipeline: extract one record with Gemini, using a
JSON schema generated from these models (TDD Part 2, "The pipeline for one
document"). The models hold text exactly as written; code turns amounts into
paise (app.domain.money.parse_inr) and checks every field, so the model never
produces a number the ledger stores (batch 2 plan, Q4)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.client import AIResult, Backend, Contents, call, load_prompt
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


class InvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    amount_text: str  # the line's amount before tax, as printed


class InvoiceExtract(BaseModel):
    """A vendor's bill or the business's own sales invoice (code decides which,
    from the seller and buyer: batch 5 plan, Q2). Every amount is text as
    printed; code turns it into paise and does the arithmetic."""

    model_config = ConfigDict(extra="forbid")

    seller_name: str
    seller_gstin: str | None
    buyer_name: str | None
    buyer_gstin: str | None
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    lines: list[InvoiceLine]
    gst_texts: list[str]  # each tax amount printed: CGST, SGST, IGST
    round_off_text: str | None  # the printed "Round off" amount with its sign, or null (D19)
    total_text: str
    payee_account_number: str | None  # bank details printed for payment, as written
    payee_ifsc: str | None
    uncertain_fields: list[str]


class StatementRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    txn_date: date
    direction: Literal["debit", "credit"]
    amount_text: str
    counterparty: str | None
    reference: str | None


class StatementExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_last4: str = Field(pattern=r"^[0-9]{4}$")
    period_from: date
    period_to: date
    opening_balance_text: str | None
    closing_balance_text: str | None
    rows: list[StatementRow]
    uncertain_fields: list[str]


class VoiceBillExtract(BaseModel):
    """A voice note about a bill: the transcript and the bill in one call (TDD
    Part 1, "AI model"). The amount is only the words spoken ("dedh lakh");
    code turns them into paise (batch 5 plan, S6), so no stored number comes
    from the model."""

    model_config = ConfigDict(extra="forbid")

    transcript: str
    vendor_name: str | None
    amount_spoken: str | None
    invoice_number: str | None
    due_date: date | None
    uncertain_fields: list[str]


EXTRACTORS: dict[str, tuple[str, type[BaseModel]]] = {
    "bank_alert": ("extract_bank_alert.v1", BankAlertExtract),
    "failure_notice": ("extract_failure.v1", FailureNoticeExtract),
    "invoice": ("extract_invoice.v1", InvoiceExtract),
    "statement": ("extract_statement.v1", StatementExtract),
    "voice_note": ("extract_voice.v1", VoiceBillExtract),
}


def prompt_version(app_config: AppConfig, doc_type: str) -> str:
    return f"{app_config.prompts.version}/{EXTRACTORS[doc_type][0]}"


def retry_note(previous: str | None, failed_checks: dict[str, str]) -> str:
    failures = "\n".join(f"- {name}: {why}" for name, why in sorted(failed_checks.items()))
    return (
        f"---\nA previous reading of this document failed these checks:\n{failures}\n"
        f"The previous answer was:\n{previous if previous is not None else '(no answer)'}\n"
        "Read the document again and return corrected JSON."
    )


def retry_context(contents: Contents, previous: str | None, failed_checks: dict[str, str]) -> Contents:
    """The document again, with the last answer and the checks it failed, so
    the next attempt can correct itself (pipeline step 4). A document with
    files gets the note as one more text part after them."""
    note = retry_note(previous, failed_checks)
    if isinstance(contents, str):
        return f"{contents}\n\n{note}"
    return [*contents, note]


def extract_document(
    doc_type: str,
    text: Contents,
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
