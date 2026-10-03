"""Money is integer paise everywhere. This module formats it for people and
parses the amounts people (and banks) write, so an AI extraction returns the
amount text exactly as written and code turns it into paise (batch 2 plan, Q4).

parse_inr is strict: it accepts the forms Indian bank alerts use and refuses
everything else. A refusal is a failed rule check, never a guess."""

from __future__ import annotations

import re
from fractions import Fraction


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


# --- amounts as people say them (voice notes; batch 5 plan, S6) -------------------------

_SAID_NUMBERS = {
    # Hindi and Hinglish, as Gemini writes them in Latin letters
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6,
    "che": 6, "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9, "das": 10, "gyarah": 11, "barah": 12,
    "baarah": 12, "terah": 13, "chaudah": 14, "pandrah": 15, "solah": 16, "satrah": 17,
    "atharah": 18, "unnees": 19, "bees": 20, "pachchees": 25, "pachees": 25, "tees": 30, "chaalis": 40,
    "chalis": 40, "pachaas": 50, "pachas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90,
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SAID_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
_SAID_SCALES = {
    "crore": 10**7, "karod": 10**7, "karor": 10**7, "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5,
    "hazaar": 1000, "hazar": 1000, "hajar": 1000, "thousand": 1000, "sau": 100, "hundred": 100,
}
# dedh 1.5 and dhai 2.5 stand alone, as does sawa 1.25 (sawa lakh); before a number, sawa adds a
# quarter (sawa do lakh = 2.25 lakh), saade a half (saade teen) and paune takes a quarter off (paune do).
# Each of these needs a scale after it: "dedh" alone is not an amount.
_SAID_WHOLE = {"dedh": Fraction(3, 2), "derh": Fraction(3, 2), "dhai": Fraction(5, 2), "dhaai": Fraction(5, 2),
               "adhai": Fraction(5, 2)}
_SAID_SHIFT = {"saade": Fraction(1, 2), "sadhe": Fraction(1, 2), "saadhe": Fraction(1, 2),
               "paune": Fraction(-1, 4), "pone": Fraction(-1, 4)}
_SAID_NOISE = {"rupees", "rupee", "rupaye", "rupaiye", "rupay", "rs", "inr", "only", "sirf", "bas", "ka", "ki", "ke",
               "and", "aur", "₹"}
_DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


def _said_number(tokens: list[str], i: int) -> tuple[Fraction, int] | None:
    t = tokens[i]
    if _DECIMAL.match(t):
        return Fraction(t), i + 1
    if t in _SAID_NUMBERS:
        n = _SAID_NUMBERS[t]
        if t in _SAID_TENS and i + 1 < len(tokens) and _SAID_NUMBERS.get(tokens[i + 1], 10) < 10:
            return Fraction(n + _SAID_NUMBERS[tokens[i + 1]]), i + 2  # twenty five
        return Fraction(n), i + 1
    return None


def _said_quantity(tokens: list[str], i: int) -> tuple[Fraction, int]:
    t = tokens[i]
    if t in _SAID_WHOLE:
        return _SAID_WHOLE[t], i + 1
    if t == "sawa":
        nxt = _said_number(tokens, i + 1) if i + 1 < len(tokens) else None
        return (nxt[0] + Fraction(1, 4), nxt[1]) if nxt else (Fraction(5, 4), i + 1)
    if t in _SAID_SHIFT:
        nxt = _said_number(tokens, i + 1) if i + 1 < len(tokens) else None
        if nxt is None:
            raise ValueError(f"{t!r} needs a number after it")
        return nxt[0] + _SAID_SHIFT[t], nxt[1]
    got = _said_number(tokens, i)
    if got is None:
        raise ValueError(f"{t!r} is not a number this app reads")
    return got


def parse_spoken_inr(text: str) -> int:
    """An amount as said in a voice note, in Hindi, Hinglish or English, ->
    int paise: "dedh lakh" is ₹1,50,000, "sawa do lakh" ₹2,25,000, "45 hazaar"
    ₹45,000, "ek lakh pachaas hazaar" and "one lakh fifty thousand" both
    ₹1,50,000. Exact (fractions, never floats). Anything it does not
    recognise raises ValueError: the owner types the amount (batch 5, Q8)."""
    if not isinstance(text, str):
        raise TypeError(f"amount text must be str, got {type(text).__name__}")
    try:
        return parse_inr(text)
    except ValueError:
        pass
    words = re.sub(r"[,/-]", " ", text.lower().replace("₹", " ")).split()
    tokens = [w.strip(".") if not _DECIMAL.match(w) else w for w in words]
    tokens = [t for t in tokens if t and t not in _SAID_NOISE]
    if not tokens:
        raise ValueError(f"no amount said: {text!r}")
    total, last_scale, i = Fraction(0), None, 0
    while i < len(tokens):
        if tokens[i] in _SAID_SCALES:
            raise ValueError(f"{tokens[i]!r} has no number before it in {text!r}")
        fraction_word = tokens[i] in _SAID_WHOLE or tokens[i] in _SAID_SHIFT or tokens[i] == "sawa"
        quantity, i = _said_quantity(tokens, i)
        scale = 1
        if i < len(tokens) and tokens[i] in _SAID_SCALES:
            scale = _SAID_SCALES[tokens[i]]
            i += 1
        elif i < len(tokens):
            raise ValueError(f"{tokens[i]!r} is out of place in {text!r}")
        if fraction_word and scale == 1:
            raise ValueError(f"{text!r} needs sau, hazaar, lakh or crore after the fraction")
        if last_scale is not None and scale >= last_scale:
            raise ValueError(f"the parts of {text!r} are not in descending order")
        total += quantity * scale
        last_scale = scale
    paise = total * 100
    if paise.denominator != 1 or paise <= 0:
        raise ValueError(f"{text!r} is not a whole number of paise above zero")
    return int(paise)
