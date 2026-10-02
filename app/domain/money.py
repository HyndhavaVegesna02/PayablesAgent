"""Money is integer paise everywhere. This module formats it for people and
parses the amounts people (and banks) write, so an AI extraction returns the
amount text exactly as written and code turns it into paise (batch 2 plan, Q4).

parse_inr is strict: it accepts the forms Indian bank alerts use and refuses
everything else. A refusal is a failed rule check, never a guess."""

from __future__ import annotations

import re


def _group_indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def format_inr(paise: int) -> str:
    """₹ in lakh grouping (₹2,82,000); paise shown only when non-zero."""
    if type(paise) is not int:
        raise TypeError(f"money must be int paise, got {type(paise).__name__}")
    sign = "-" if paise < 0 else ""
    rupees, rem = divmod(abs(paise), 100)
    text = f"{sign}₹{_group_indian(rupees)}"
    return f"{text}.{rem:02d}" if rem else text


# "Rs.1,20,000.00", "INR 120000", "₹ 1,20,000", "Rs. 45,000/-", "1,200,000.50"
_INR = re.compile(
    r"(?:(?:Rs\.?|INR|₹)\s*)?"
    r"(?P<rupees>[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}"  # Indian grouping: 1,20,000
    r"|[0-9]{1,3}(?:,[0-9]{3})+"  # western grouping: 120,000
    r"|[0-9]+)"  # no grouping: 120000
    r"(?:\.(?P<paise>[0-9]{1,2}))?"
    r"(?:\s*/-)?",
    re.IGNORECASE,
)


def parse_inr(text: str) -> int:
    """Rupees as written -> int paise. Raises ValueError for anything else:
    words ("1.2 lakh"), signs, three decimal places, letters for digits."""
    if not isinstance(text, str):
        raise TypeError(f"amount text must be str, got {type(text).__name__}")
    m = _INR.fullmatch(text.strip())
    if m is None:
        raise ValueError(f"not an amount in rupees: {text!r}")
    rupees = int(m.group("rupees").replace(",", ""))
    paise = m.group("paise") or "0"
    return rupees * 100 + int(paise.ljust(2, "0"))
