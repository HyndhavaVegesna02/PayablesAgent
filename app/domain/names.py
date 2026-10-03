"""Party names as banks, vendors and people write them. Pure, so the
reconciler and the rule checks (app/validate) share one rule for "the same
name"."""

from __future__ import annotations

import re

_NOISE_WORDS = frozenset({"PVT", "PRIVATE", "LTD", "LIMITED", "MS"})  # and M/S, removed first


def normalise_name(name: str | None) -> str:
    """Upper case, punctuation removed, and PVT, LTD, M/S and the like dropped."""
    if not name:
        return ""
    text = re.sub(r"\bM\s*/\s*S\b", " ", name.upper())
    words = re.sub(r"[^A-Z0-9]+", " ", text).split()
    return " ".join(w for w in words if w not in _NOISE_WORDS)


def name_matches(counterparty: str | None, names: list[str]) -> bool:
    """A name matches when it equals, or contains, the vendor's name or an alias."""
    seen = normalise_name(counterparty)
    if not seen:
        return False
    for n in names:
        want = normalise_name(n)
        if want and (seen == want or f" {want} " in f" {seen} "):
            return True
    return False
