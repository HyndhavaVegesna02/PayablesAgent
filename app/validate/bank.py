"""Vendor bank details as invoices print them (batch 5 plan, S4). Only the
last four digits of an account are kept on record, as a mask; a change is any
difference in those digits or in the IFSC."""

from __future__ import annotations

import re

_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def account_last4(text: str | None) -> str | None:
    digits = re.sub(r"[^0-9]", "", text or "")
    return digits[-4:] if len(digits) >= 4 else None


def account_mask(text: str | None) -> str | None:
    last4 = account_last4(text)
    return None if last4 is None else f"XXXX{last4}"


def normalise_ifsc(text: str | None) -> str | None:
    ifsc = "".join((text or "").split()).upper()
    return ifsc if _IFSC.match(ifsc) else None


def differs(on_record_mask: str | None, on_record_ifsc: str | None, last4: str | None, ifsc: str | None) -> bool:
    """True when a printed detail contradicts one on record. A detail missing
    on either side can't contradict anything."""
    recorded4 = account_last4(on_record_mask)
    return bool((recorded4 and last4 and recorded4 != last4) or (on_record_ifsc and ifsc and on_record_ifsc != ifsc))


def describe(mask_or_account: str | None, ifsc: str | None) -> str:
    """"account ending 4410, IFSC SBIN0001234", leaving out what is unknown."""
    last4 = account_last4(mask_or_account)
    return ", ".join(v for v in (f"account ending {last4}" if last4 else "", f"IFSC {ifsc}" if ifsc else "") if v)


def change_question(party_name: str, on_record_mask: str | None, on_record_ifsc: str | None,
                    last4: str | None, ifsc: str | None) -> str:
    return (f"A bill from {party_name} gives different bank details: {describe(last4, ifsc)} "
            f"(on record: {describe(on_record_mask, on_record_ifsc)}). Vendor bank details change pending: "
            "verify before paying. Check with the vendor by phone, on a number you already have, before approving.")
