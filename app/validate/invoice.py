"""The checks for an invoice read from an email, photo or PDF (TDD Part 1,
"Rule checks"; batch 5 plan, S3). Pure: whatever the checks need to know
about the ledger comes in as a lookup function from the caller.

The record it returns is in the typed entry's shape (app/web/actions.py
parse_entry), so the owner confirms it on the same form, through the same
checks again (TDD: a bill from a photo, PDF or voice note becomes CONFIRMED
only after the owner checks it)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.money import parse_inr
from app.domain.names import normalise_name
from app.validate import CHECK_NAMES, NOT_APPLICABLE, PASSED, failed, skipped
from app.validate.arithmetic import check_invoice_arithmetic
from app.validate.duplicates import normalise_reference
from app.validate.gstin import check_gstin, normalise_gstin

_MINUS = ("-", "−", "(-)", "less")


@dataclass(frozen=True)
class InvoiceKey:
    """What makes two invoices the same one (TDD "Duplicates": same vendor and
    invoice number, or same amount, date and reference)."""

    party: str  # as written
    party_gstin: str | None
    invoice_number: str | None  # normalised
    amount_paise: int
    invoice_date: date | None


# Describes the invoice already recorded or waiting ("Ashirwad Paper Suppliers
# invoice AP/2610/118 is already recorded"), or None.
ExistingInvoice = Callable[[InvoiceKey], str | None]


@dataclass(frozen=True)
class InvoiceRecord:
    kind: Literal["bill", "invoice"]
    record: dict[str, Any]  # the typed entry's shape, JSON-ready
    key: InvoiceKey
    payee_account: str | None
    payee_ifsc: str | None


def signed_inr(text: str) -> int:
    """A printed round-off, with its sign ("-0.40", "(-) 0.40", "Less 0.40")."""
    t = text.strip()
    for m in _MINUS:
        if t.lower().startswith(m):
            return -parse_inr(t[len(m):].strip())
    return parse_inr(t.lstrip("+").strip())


def _amounts(texts: list[str], what: str, problems: list[str]) -> list[int]:
    out = []
    for t in texts:
        try:
            out.append(parse_inr(t))
        except ValueError:
            problems.append(f"{what} {t!r} is not an amount in rupees")
    return out


def _which_side(x: BaseModel, business_name: str) -> tuple[Literal["bill", "invoice"] | None, str]:
    """A vendor's bill to the business, or the business's own sales invoice
    (Q2): decided by code from the names, never by the model."""
    us = normalise_name(business_name)
    if normalise_name(x.seller_name) == us:
        return "invoice", x.buyer_name or ""
    if x.buyer_name is None or normalise_name(x.buyer_name) == us:
        return "bill", x.seller_name
    return None, x.seller_name


def check_invoice(
    extract: BaseModel | None,
    schema_error: str | None,
    business_name: str,
    existing: ExistingInvoice,
) -> tuple[dict[str, str], InvoiceRecord | None, dict[str, Any]]:
    """The checks, the record when every check passed, and the best reading so
    far (the record's fields that could be read) for the owner's form."""
    if extract is None:
        checks = {name: skipped("the reply did not match the schema") for name in CHECK_NAMES}
        checks.update(schema=failed(schema_error or "no reply"), account=NOT_APPLICABLE, balance=NOT_APPLICABLE,
                      statement_arithmetic=NOT_APPLICABLE)
        return checks, None, {}
    x = extract
    checks = {name: NOT_APPLICABLE for name in CHECK_NAMES}
    checks["schema"] = PASSED

    problems: list[str] = []
    total = None
    try:
        total = parse_inr(x.total_text)
        if total <= 0:
            problems.append(f"total {x.total_text!r} is not more than zero")
    except ValueError:
        problems.append(f"total {x.total_text!r} is not an amount in rupees")
    lines = _amounts([ln.amount_text for ln in x.lines], "line amount", problems)
    gst = _amounts(x.gst_texts, "GST amount", problems)
    round_off = None
    if x.round_off_text is not None:
        try:
            round_off = signed_inr(x.round_off_text)
        except ValueError:
            problems.append(f"round-off {x.round_off_text!r} is not an amount in rupees")
    checks["amount"] = failed("; ".join(problems)) if problems else PASSED

    if problems or total is None:
        checks["invoice_arithmetic"] = skipped("needs every amount read")
    else:
        checks["invoice_arithmetic"] = check_invoice_arithmetic(lines, gst, total, round_off)

    kind, party = _which_side(x, business_name)
    party_gstin = x.seller_gstin if kind != "invoice" else x.buyer_gstin
    gstins = [check_gstin(x.seller_gstin, required=bool(x.gst_texts)), check_gstin(x.buyer_gstin)]
    bad = [g for g in gstins if g.startswith("failed")]
    checks["gstin"] = bad[0] if bad else (PASSED if PASSED in gstins else NOT_APPLICABLE)

    if x.invoice_date and x.due_date and x.due_date < x.invoice_date:
        checks["dates"] = failed(f"the due date {x.due_date} is before the invoice date {x.invoice_date}")
    else:
        checks["dates"] = PASSED

    number = normalise_reference(x.invoice_number)
    key = None
    if total is not None and party:
        key = InvoiceKey(party, normalise_gstin(party_gstin), number, total, x.invoice_date)
        dup = existing(key)
        checks["duplicates"] = PASSED if dup is None else failed(dup)
    else:
        checks["duplicates"] = skipped("needs the party and the total")

    unsure = sorted(x.uncertain_fields)
    if kind is None:
        unsure.append(f"whether this is a bill or a sales invoice (neither {x.seller_name!r} "
                      f"nor {x.buyer_name!r} is {business_name})")
    checks["confidence"] = PASSED if not unsure else failed(f"the model is unsure of {', '.join(unsure)}")

    reading: dict[str, Any] = {
        "kind": kind or "bill", "party": party, "invoice_number": x.invoice_number,
        "invoice_date": x.invoice_date.isoformat() if x.invoice_date else None, "amount_paise": total,
        "due_date": x.due_date.isoformat() if x.due_date else None,
    }
    if reading["kind"] == "bill":
        reading["priority"] = "normal"
    else:
        reading.update(expected_date=None, confidence="EXPECTED")
    checks = {name: checks[name] for name in CHECK_NAMES}
    if any(v.startswith(("failed", "skipped")) for v in checks.values()) or key is None or kind is None:
        return checks, None, reading
    return checks, InvoiceRecord(kind, reading, key, x.payee_account_number, x.payee_ifsc), reading
