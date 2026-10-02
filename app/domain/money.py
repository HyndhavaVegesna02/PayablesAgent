"""Money is integer paise everywhere; this module only formats it for people."""

from __future__ import annotations


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
