"""Pydantic models for ledger records (TDD Part 2, "Database schema").

`*New` models are what the ledger writer accepts to create a record; the
others mirror a stored row. Money fields are StrictInt, so a float amount is
refused at the boundary instead of being silently truncated."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Paise = Annotated[StrictInt, Field(gt=0)]
SignedPaise = StrictInt
Priority = Literal["statutory", "critical", "normal", "flexible"]
PayableStatus = Literal[
    "DRAFT", "CONFIRMED", "PLANNED", "PAYMENT_EXPECTED", "PAID", "REOPENED", "REVIEW", "SPLIT"
]
Confidence = Literal["CONFIRMED", "COMMITTED", "EXPECTED", "UNKNOWN"]
BankTxnStatus = Literal["UNMATCHED", "MATCHED", "EXPLAINED", "ADJUSTMENT", "REVERSED"]
TaxType = Literal["GST", "TDS", "PF", "ESI", "ADVANCE_TAX"]
AmountStatus = Literal["CONFIRMED", "ESTIMATED", "MISSING"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PayableNew(_Record):
    business_id: StrictInt
    party_id: StrictInt | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    amount_paise: Paise
    due_date: date
    priority: Priority
    grace_days: Annotated[StrictInt, Field(ge=0)] = 0
    discount_paise: Paise | None = None
    discount_by: date | None = None
    source_document_id: StrictInt | None = None

    @model_validator(mode="after")
    def _discount_is_coherent(self) -> "PayableNew":
        # The planner reads discount_paise as paise saved if paid by discount_by.
        if (self.discount_paise is None) != (self.discount_by is None):
            raise ValueError("discount_paise and discount_by are set together or not at all")
        if self.discount_paise is not None and self.discount_paise >= self.amount_paise:
            raise ValueError("a discount must be smaller than the bill")
        return self


class Payable(PayableNew):
    id: StrictInt
    parent_payable_id: StrictInt | None
    status: PayableStatus
    planned_date: date | None
    approved_by: StrictInt | None
    approved_at: str | None
    matched_txn_id: StrictInt | None
    version: StrictInt


class ReceivableNew(_Record):
    business_id: StrictInt
    party_id: StrictInt | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    amount_paise: Paise
    due_date: date | None = None
    expected_date: date | None = None
    confidence: Literal["COMMITTED", "EXPECTED", "UNKNOWN"]
    source_document_id: StrictInt | None = None


class Receivable(ReceivableNew):
    id: StrictInt
    confidence: Confidence  # type: ignore[assignment]
    matched_txn_id: StrictInt | None
    version: StrictInt


class BankTxnNew(_Record):
    account_id: StrictInt
    direction: Literal["debit", "credit"]
    amount_paise: Paise
    txn_date: date
    value_date: date | None = None
    description: str | None = None
    counterparty: str | None = None
    party_id: StrictInt | None = None
    reference: str | None = None
    balance_after_paise: SignedPaise | None = None
    dedup_key: str
    source_document_id: StrictInt | None = None
    candidate_id: StrictInt | None = None
    status: Literal["UNMATCHED", "ADJUSTMENT"]


class BankTxn(BankTxnNew):
    id: StrictInt
    status: BankTxnStatus  # type: ignore[assignment]


class TaxObligationNew(_Record):
    business_id: StrictInt
    tax_type: TaxType
    period: str
    due_date: date
    amount_paise: Paise | None
    amount_status: AmountStatus
    challan_document_id: StrictInt | None = None

    @model_validator(mode="after")
    def _amount_matches_status(self) -> "TaxObligationNew":
        if (self.amount_paise is None) != (self.amount_status == "MISSING"):
            raise ValueError("amount_paise is NULL exactly when amount_status is MISSING")
        return self


class TaxObligation(TaxObligationNew):
    id: StrictInt
    payable_id: StrictInt | None

