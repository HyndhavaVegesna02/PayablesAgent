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
# The unit said after an amount (PO D28). The number words decide the amount; the unit is noise, and so is
# a unit cut short ("dedh lakh rup"): a prefix of at least three letters of one of these, never another word.
CURRENCY_WORDS = ("rupaye", "rupees", "rupee", "rupiya", "rupaiye", "rupaya", "rupaiya", "rupye", "rupay", "rs", "inr")
_SAID_NOISE = {*CURRENCY_WORDS, "only", "sirf", "bas", "ka", "ki", "ke", "and", "aur", "₹"}
_DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


def _is_currency_word(word: str) -> bool:
    w = word.lower().strip(".")
    return w in CURRENCY_WORDS or (len(w) >= 3 and w.isalpha() and any(c.startswith(w) for c in CURRENCY_WORDS))


def without_currency_word(text: str) -> str:
    """The amount as said, without a currency word (or the start of one) at
    its end: "dedh lakh rup" -> "dedh lakh". Anything else at the end stays,
    and is refused by the parser as before."""
    words = text.split()
    while words and _is_currency_word(words[-1]):
        words.pop()
    return " ".join(words)


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
    text = without_currency_word(text)
    if re.sub(r"^(?:₹|rs\.?|inr)\s*", "", text.strip().lower()).startswith(("-", "\u2212", "minus")):
        raise ValueError(f"a negative amount is not a bill: {text!r}")
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
        if scale == 1 and last_scale is not None and last_scale > 1000 and quantity < 1000:
            # "ek lakh pachaas" usually means 1.5 lakh, not 1,00,050: too ambiguous to read
            raise ValueError(f"{text!r} leaves out the hazaar or sau after its last number")
        total += quantity * scale
        last_scale = scale
    paise = total * 100
    if paise.denominator != 1 or paise <= 0:
        raise ValueError(f"{text!r} is not a whole number of paise above zero")
    return int(paise)


# Words that are part of a spoken number but that parse_spoken_inr doesn't read: Hindi 11-99 as people
# write them, other spellings, signs and paise (batch 11 review, round 2). Only membership is used, never a
# value: a word here makes the amount around it unreadable, so a gap in this list can never become a wrong
# amount through it, and an extra word can only send a bill to the owner.
_NUMBER_LIKE = {
    "dus", "gyaarah", "gyara", "baara", "tera", "chauda", "pandra", "sola", "satra", "athaarah", "athara",
    "unees", "unnis", "unis", "ikkees", "ikkis", "ikis", "baees", "bais", "baais", "bayees", "teis", "teyees",
    "tais", "chaubees", "chaubis", "pachis", "pachchis", "chhabbees", "chhabbis", "chabbis", "sattaees",
    "sattais", "atthaees", "atthais", "athais", "untees", "untis", "ikattees", "ikattis", "iktees", "iktis",
    "battees", "battis", "taintees", "tentis", "taintis", "chauntees", "chautis", "chontis", "paintees",
    "paintis", "chhattees", "chhattis", "chattis", "saintees", "saintis", "adtees", "artees", "adtis", "artis",
    "untalees", "untalis", "chaalees", "chalees", "iktalees", "iktalis", "bayalees", "bayalis", "taintalees",
    "taintalis", "tetalis", "chavalees", "chauvalis", "chawalis", "paintalees", "paintalis", "chhiyalees",
    "chhiyalis", "saintalees", "saintalis", "adtalees", "artalis", "adtalis", "unchaas", "unchas", "ikyaavan",
    "ikyavan", "baavan", "bavan", "tirpan", "trepan", "chauvan", "chouvan", "pachpan", "chhappan", "chappan",
    "sattaavan", "sattavan", "atthaavan", "athavan", "unsath", "unsaath", "iksath", "eksath", "baasath",
    "basath", "tirsath", "tresath", "chausath", "chosath", "painsath", "chhiyasath", "chiyasath", "sadsath",
    "sarsath", "adsath", "arsath", "unhattar", "ikhattar", "bahattar", "tihattar", "chauhattar", "pachhattar",
    "pachattar", "chhihattar", "chihattar", "satattar", "sathattar", "athattar", "athhattar", "unaasi", "unasi",
    "ikyaasi", "ikyasi", "bayaasi", "bayasi", "tiraasi", "tirasi", "chauraasi", "chaurasi", "pachaasi",
    "pachasi", "chhiyaasi", "chhiyasi", "sattaasi", "sattasi", "atthaasi", "athasi", "navaasi", "navasi",
    "nawasi", "nabe", "nabbay", "ikyaanave", "ikyanve", "baanave", "banve", "tiraanave", "tiranve",
    "chauraanave", "chauranve", "pachaanave", "pachanve", "chhiyaanave", "chhiyanve", "sattaanave", "sattanve",
    "atthaanave", "athanve", "ninyaanave", "ninyanve", "sava", "savaa", "saare", "saarhe", "sarhe", "sade",
    "paav", "aadha", "adha", "half", "quarter", "zero", "shunya", "minus", "naught",
    "laakh", "laakhs", "hajaar", "hazaaar", "hazaron", "crores", "karoda", "thousands", "hundreds", "million",
    "billion",
}
_SCALE_LIKE = {*_SAID_SCALES, "laakh", "laakhs", "hajaar", "hazaaar", "hazaron", "crores", "karoda",
               "thousands", "hundreds", "million", "billion"}
# Short scales, written after digits ("50 k", "1.5 L", "2 cr"): the parser doesn't read them, so the amount
# they end is unreadable. Only straight after digits, where they can't be another word.
_SHORT_SCALES = {"k", "l", "lk", "lkh", "lks", "cr", "crs", "m", "mn"}
# Letters written onto digits that make them money ("Rs1,50,000", "150000rs", "1.5L", "2cr", "50hazaar"), as
# against an invoice number, an ordinal or a date ("AP/2610/150", "5th", "covid-19"). A rupee word or its
# start counts too.
_ON_DIGITS = {"rs", "inr", "k", "l", "lk", "lkh", "lks", "lac", "lacs", "lakh", "lakhs", "cr", "crs", "crore",
              "crores", "m", "mn", "hazaar", "hazar", "hajar", "hajaar", "thousand", "hundred", "sau"}
# Words that make a number a range or a guess, so the amount it touches is unreadable (round 3): after an
# amount ("do lakh se zyada", "25 to 30 lakh", "ek lakh plus GST"), or before one ("lagbhag do lakh").
_HEDGE_AFTER = {"to", "ya", "or", "se", "zyada", "jyada", "jada", "kam", "plus", "upar", "adhik", "till", "upto",
                "approx"}
_HEDGE_AFTER_UNIT = _HEDGE_AFTER - {"to", "ya", "or", "till"}  # after "rupaye": "to" is "so", not a range
_HEDGE_BEFORE = {"lagbhag", "lagbhagh", "kareeb", "karib", "kareeban", "takreeban", "taqreeban", "around",
                 "about", "approx", "approximately", "roughly", "almost", "nearly", "over", "under", "upto",
                 "above", "below", "max", "maximum", "min", "minimum"}
_DASHES = {"-", "–", "—", "~"}


def _digits(word: str) -> bool:
    return any(c.isdigit() for c in word)


def _number_like(word: str) -> bool:
    """A word that is, or is part of, a number: any word with a digit in it, a number word (read by the
    parser or not), or a compound of them ("twenty-five", "dedh-lakh", "lakh-ish"; not "de-do")."""
    w = word.replace("_", "")
    if (_digits(w) or w in _SAID_NUMBERS or w in _SAID_SCALES or w in _SAID_WHOLE or w in _SAID_SHIFT
            or w == "sawa" or w in _NUMBER_LIKE):
        return True
    parts = [p for p in re.split(r"[-/]", w) if p]
    return len(parts) > 1 and (all(_number_like(p) for p in parts) or any(p in _SCALE_LIKE for p in parts))


def _money_shaped(word: str) -> bool:
    """By form: a comma grouping, ₹, a scale or rupee word, paise, a mark after digits ("/-", "/=", "-"), or
    letters on digits that make them money (_ON_DIGITS)."""
    w = word.replace("_", "")
    if "_" in word or "₹" in w or w in ("paise", "paisa") or w in _SCALE_LIKE or _is_currency_word(w):
        return True
    if _digits(w) and (w.endswith(("/", "-", "=")) or any(r in _ON_DIGITS or _is_currency_word(r)
                                                          for r in re.findall(r"[a-z]+", w))):
        return True
    parts = [p for p in re.split(r"[-/]", w) if p]
    return len(parts) > 1 and any(_money_shaped(p) for p in parts)


def money_said(text: str) -> list[int | None]:
    """Every money-shaped amount a transcript says, in paise, in order (CHG-037,
    PO D29); None for one code can't read in full. The transcript is cut into
    clusters, each a run of number words ("ka", "aur", "only", commas, and an
    Rs or rupee word before it may sit inside one), and each cluster is read
    whole by parse_spoken_inr or not at all: never a leading part of it.
    "do lakh pachaas hazaar" is ₹2,50,000; "ek lakh pachaas" (ambiguous),
    "ek lakh baees hazaar" (a word the parser doesn't read), "25 to 30 lakh"
    and "lagbhag do lakh" (a range or a guess) are None.

    A rupee word after an amount, or a sentence end, closes it. A number
    word straight after that (nothing but a connector between) belongs to it,
    so the amount is None: "ek lakh rupaye pachaas". A comma after a rupee
    word is a clean end ("dedh lakh rupaye, paanch November"). After digits
    only a scale word goes on: another number straight after them makes the
    amount None ("Rs 1,00,000 pachaas"), and after a comma it starts its own
    ("Rs 1,50,000, 5 November").

    Money-shaped means a scale word, a currency word, ₹, paise, Rs or "/-" on
    the digits, or digits grouped with commas ("1,50,000"); a bare number (a
    date, an invoice number, a count) is not counted."""
    text = text.lower().replace("_", " ")
    text = re.sub(r"(?<=\d),(?=\d)", "_", text)  # "1,50,000": one word, its grouping remembered
    text = re.sub(r"\b(rs|inr)\.", r"\1 ", text)
    text = re.sub(r"(?<!\d)\.|\.(?!\d)|[!?;:\n]", " . ", text)
    tokens = re.findall(r"₹?[\w./=-]*[\w/=-]|[^\w\s]", text)

    found: list[int | None] = []
    cluster: list[str] = []  # the open cluster's words, "_" marking a comma grouping
    numbers: list[str] = []  # its number words
    comma = False  # a comma since its last number word
    ranged = False  # a range or guess word in it: it is read whole, as one
    watch: int | None = None  # a closed amount that a number word next would make unreadable
    soft = False  # whether a comma ends the watch (after a rupee word; not after a sentence end)

    def close() -> int | None:
        nonlocal cluster, numbers, comma, ranged
        raw, had = cluster, bool(numbers)
        cluster, numbers, comma, ranged = [], [], False, False
        if not had or not any(_money_shaped(w) for w in raw):
            return None  # no number, or a bare one: not money
        try:
            found.append(parse_spoken_inr(" ".join(w.replace("_", "") for w in raw)))
        except ValueError:
            found.append(None)
        return len(found) - 1

    def unreadable(i: int | None) -> None:
        if i is not None:
            found[i] = None

    for tok in tokens:
        w = tok.replace("_", "")
        if tok == ".":  # a sentence end
            closed = close()
            if closed is not None:
                watch, soft = closed, False
        elif tok in _DASHES or tok == "+":
            if numbers:
                cluster.append("to")  # "25 - 30 lakh", "ek lakh + GST": a range, or not the whole
                ranged = True
            elif tok == "+" and watch is not None:
                unreadable(watch)  # "Bill ek lakh rupaye + GST"
                watch = None
        elif not any(c.isalnum() or c == "₹" for c in tok):  # a comma or other mark: inside an amount, it goes on
            comma = comma or bool(numbers)
            if soft:
                watch = None
        elif (_is_currency_word(w) or w == "₹") and not _digits(w):
            cluster.append(tok)
            if numbers:  # the unit after an amount closes it
                closed = close()
                if closed is not None:
                    watch, soft = closed, True
        elif (_number_like(tok) or (w in _SHORT_SCALES and numbers and _digits(numbers[-1]))
              or (w in ("paise", "paisa") and numbers)):  # "paise" alone is money in general, not an amount
            if watch is not None:
                unreadable(watch)  # "ek lakh rupaye pachaas": the rest of it came after the unit
                watch = None
            if numbers and comma and "_" in tok and not _digits(numbers[-1]):
                close()  # "do lakh, 50,000 advance": a written amount after a comma starts its own
            if numbers and _digits(numbers[-1]) and w not in _SCALE_LIKE and w not in _SHORT_SCALES and not ranged:
                if comma:
                    close()  # "Rs 1,50,000, 5 November": two
                else:
                    unreadable(close())  # "Rs 1,00,000 pachaas": the rest of it, unread
            cluster.append(tok)
            numbers.append(w)
        elif not numbers and watch is not None and w in _HEDGE_AFTER_UNIT:
            unreadable(watch)  # "do lakh rupaye se zyada", "ek lakh. Plus GST."
            watch = None
        elif w in _HEDGE_BEFORE or (numbers and w in _HEDGE_AFTER):
            cluster.append(tok)  # the parser refuses it, so the amount it touches is None
            ranged = True
        elif w in _SAID_NOISE:
            if cluster:
                cluster.append(tok)
        else:  # an ordinary word ends any amount, and nothing after it belongs to one before it
            close()
            watch = None
    close()
    return found
