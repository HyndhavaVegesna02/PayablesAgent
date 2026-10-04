"""The checks for a bill told in a voice note (batch 5 plan, S6). The model
writes down what was said; code turns the spoken amount into paise
(parse_spoken_inr), so no stored number comes from the model. That amount
passes only when it equals, in paise, an amount code reads in full from the
transcript (amounts_said; CHG-037): never on the words alone. An amount the
code can't read, or one the transcript doesn't say, is a failed check: the
owner types it, with the transcript beside the form (Q8). Pure, like every
check here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain.money import amounts_said, parse_spoken_inr
from app.validate import CHECK_NAMES, NO_DUE_DATE, NOT_APPLICABLE, PASSED, failed, skipped
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
            spoken = parse_spoken_inr(x.amount_spoken)
        except ValueError:
            checks["amount"] = failed(f"{x.amount_spoken!r} is not an amount this app can read from what was "
                                      "said: type it in")
        else:
            if spoken in amounts_said(x.transcript):  # equal paise, never the model's words alone
                amount = spoken
                checks["amount"] = PASSED
            else:
                checks["amount"] = failed(f"{x.amount_spoken!r} is not an amount said in the voice note, read in "
                                          "full: type it in")
    checks["dates"] = PASSED if x.due_date is not None else failed(NO_DUE_DATE)
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
