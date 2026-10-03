"""The checks for a bill told in a voice note (batch 5 plan, S6). The model
writes down what was said; code turns the spoken amount into paise
(parse_spoken_inr), so no stored number comes from the model. An amount the
code can't read is a failed check: the owner types it, with the transcript
beside the form (Q8). Pure, like every check here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain.money import parse_spoken_inr
from app.validate import CHECK_NAMES, NOT_APPLICABLE, PASSED, failed, skipped
from app.validate.duplicates import normalise_invoice_number
from app.validate.invoice import ExistingInvoice, InvoiceKey, InvoiceRecord


def check_voice(
    extract: BaseModel | None,
    schema_error: str | None,
    existing: ExistingInvoice,
) -> tuple[dict[str, str], InvoiceRecord | None, dict[str, Any]]:
    if extract is None:
        checks = {name: NOT_APPLICABLE for name in CHECK_NAMES}
        checks.update(schema=failed(schema_error or "no reply"),
                      **{n: skipped("the reply did not match the schema") for n in ("amount", "duplicates",
                                                                                     "confidence")})
        return checks, None, {}
    x = extract
    checks = {name: NOT_APPLICABLE for name in CHECK_NAMES}
    checks["schema"] = PASSED
    amount = None
    if x.amount_spoken is None:
        checks["amount"] = failed("no amount was said")
    else:
        try:
            if " ".join(x.amount_spoken.lower().split()) not in " ".join(x.transcript.lower().split()):
                raise ValueError("not said")  # the words must be the ones said, not the model's own figure
            amount = parse_spoken_inr(x.amount_spoken)
            checks["amount"] = PASSED
        except ValueError:
            checks["amount"] = failed(f"{x.amount_spoken!r} is not an amount this app can read from what was "
                                      "said: type it in")
    if x.due_date is not None:
        checks["dates"] = PASSED
    if amount is not None and x.vendor_name:
        dup = existing(InvoiceKey(x.vendor_name, None, normalise_invoice_number(x.invoice_number), amount, None))
        checks["duplicates"] = PASSED if dup is None else failed(dup)
    else:
        checks["duplicates"] = skipped("needs the vendor and the amount")
    unsure = sorted(x.uncertain_fields) + ([] if x.vendor_name else ["who the bill is from"])
    checks["confidence"] = PASSED if not unsure else failed(f"the model is unsure of {', '.join(unsure)}")
    reading: dict[str, Any] = {
        "kind": "bill", "party": x.vendor_name or "", "invoice_number": x.invoice_number, "invoice_date": None,
        "amount_paise": amount, "due_date": x.due_date.isoformat() if x.due_date else None, "priority": "normal",
    }
    if any(v.startswith(("failed", "skipped")) for v in checks.values()):
        return checks, None, reading
    key = InvoiceKey(x.vendor_name, None, normalise_invoice_number(x.invoice_number), amount, None)
    return checks, InvoiceRecord("bill", reading, key, None, None), reading
