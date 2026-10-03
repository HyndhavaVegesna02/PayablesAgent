"""The arithmetic checks (TDD Part 1, "Rule checks"). Every amount is int
paise, turned from the text as written by code before it gets here, so the
sums are exact.

- Invoice arithmetic: line items plus GST equal the invoice total. Exact to
  the paise, with one allowance (PO decision D19): an explicit "Round off"
  line printed on the invoice, of at most ₹1.00 either way, counts as a line
  item. Any other difference fails.
- Statement arithmetic: opening balance plus credits minus debits equals the
  closing balance."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.money import format_inr
from app.validate import NOT_APPLICABLE, PASSED, failed

MAX_ROUND_OFF_PAISE = 100  # D19: ₹1.00


def _ints(values: Sequence[int]) -> None:
    for v in values:
        if type(v) is not int:
            raise TypeError(f"money must be int paise, got {type(v).__name__}")


def check_invoice_arithmetic(lines: Sequence[int], gst: Sequence[int], total: int,
                             round_off: int | None = None) -> str:
    """`lines` are the item amounts before tax, `gst` every tax amount printed
    (CGST, SGST, IGST lines), `round_off` the printed round-off line (signed)
    or None when the invoice has none. No item lines: not_applicable, since
    there is nothing to add up."""
    _ints([*lines, *gst, total, *([] if round_off is None else [round_off])])
    if not lines:
        return NOT_APPLICABLE
    if round_off is not None and abs(round_off) > MAX_ROUND_OFF_PAISE:
        return failed(f"the round-off of {format_inr(round_off)} is more than {format_inr(MAX_ROUND_OFF_PAISE)}")
    items, tax = sum(lines), sum(gst)
    added = items + tax + (round_off or 0)
    if added != total:
        rounding = f" + round-off {format_inr(round_off)}" if round_off else ""
        return failed(f"items {format_inr(items)} + GST {format_inr(tax)}{rounding} = {format_inr(added)}, "
                      f"but the total is {format_inr(total)}")
    return PASSED


def check_statement_arithmetic(opening: int | None, credits: Sequence[int], debits: Sequence[int],
                               closing: int | None) -> str:
    if opening is None or closing is None:
        return failed("the statement's " + ("opening" if opening is None else "closing") + " balance could not be read")
    _ints([opening, closing, *credits, *debits])
    expected = opening + sum(credits) - sum(debits)
    if expected != closing:
        return failed(f"opening {format_inr(opening)} + credits {format_inr(sum(credits))} - debits "
                      f"{format_inr(sum(debits))} = {format_inr(expected)}, but the closing balance is "
                      f"{format_inr(closing)}")
    return PASSED
