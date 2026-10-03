"""The GSTIN check (TDD Part 1, "Rule checks": correct format and a valid
check digit).

A GSTIN is 15 characters: a 2-digit state code, the holder's 10-character
PAN, an entity code (1-9, then A-Z), the letter Z, and a check character.
The check character is GSTN's mod-36 scheme over the first 14: each
character's value (0-9, then A=10 … Z=35) is multiplied by 1 and 2 in turn
from the left, each product contributes its base-36 digits (product // 36 +
product % 36), and the check is (36 - sum % 36) % 36. The GST portal's
published sample 27AAPFU0939F1ZV is the independent test vector
(tests/test_validate_gstin.py)."""

from __future__ import annotations

import re

from app.validate import NOT_APPLICABLE, PASSED, failed

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FORMAT = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def normalise_gstin(text: str | None) -> str | None:
    """Upper case, spaces removed; None for nothing written."""
    if text is None:
        return None
    g = "".join(text.split()).upper()
    return g or None


def check_character(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return ALPHABET[(36 - total % 36) % 36]


def check_gstin(text: str | None, *, required: bool = False) -> str:
    """`required` is True when the document shows the party is registered (a
    tax invoice with GST charged): then a GSTIN that can't be read fails. A
    document that carries none is otherwise not_applicable."""
    g = normalise_gstin(text)
    if g is None:
        return failed("the GSTIN could not be read") if required else NOT_APPLICABLE
    if not _FORMAT.match(g):
        return failed(f"{g} is not a GSTIN (15 characters: state, PAN, entity, Z, check)")
    expected = check_character(g[:14])
    if g[14] != expected:
        return failed(f"{g}: check character should be {expected}")
    return PASSED
