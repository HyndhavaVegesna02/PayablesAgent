"""The voice amount check compares numbers, not text (CHG-037; PO D29). Code
reads every money-shaped amount the transcript says, each in full; the bill
passes only when the voice note says exactly one (said once or more) and the
paise read from the model's amount_spoken equal it. A leading part of what was
said, a run the parser refuses, a bare number (a date, an invoice number), or
a second amount all go to the owner, who types it beside the transcript."""

import pytest

from app.ai.extract import VoiceBillExtract
from app.domain.money import money_said
from app.validate.voice import check_voice
from tests.test_voice import NOTE


def _check(transcript, spoken):
    note = VoiceBillExtract.model_validate({**NOTE, "transcript": transcript, "amount_spoken": spoken})
    return check_voice(note, None, lambda key: None)


def _flagged(transcript, spoken):
    checks, record, reading = _check(transcript, spoken)
    assert checks["amount"].startswith("failed") and checks["amount"].endswith(": type it in"), checks["amount"]
    assert record is None and reading["amount_paise"] is None  # the owner types it, beside the transcript
    return checks["amount"]


# (transcript, amount_spoken, money_said(transcript)): each passed one check or the other before.
FLAGGED = [
    # a leading part of what was said (the substring check passed these)
    ("Sharma Packaging ka bill, dedh lakh pachaas hazaar rupaye, 5 November tak.", "dedh lakh", [20_000_000]),
    ("Ashirwad Paper ka bill hai do lakh pachaas hazaar ka, invoice AP/2610/150.", "do lakh", [25_000_000]),
    ("Kumar ji, bees hazaar paanch sau rupaye, kal tak dena hai.", "bees hazaar", [2_050_000]),
    ("Total ek lakh pachaas hazaar rupees.", "ek lakh", [15_000_000]),
    ("Bill of 1,50,500 rupees from Ganesh Hardware.", "1,50,000", [15_050_000]),
    # a run the parser refuses is no amount, never its leading part (batch 11 review, critical)
    ("Sharma ka bill do lakh pachaas, 5 November tak.", "do lakh", [None]),
    ("Ashirwad ka bill ek lakh pachaas hai.", "ek lakh", [None]),
    ("Ashirwad ka bill ek lakh pachaas hai.", "1,00,000", [None]),
    ("Bill ek lakh, pachaas.", "ek lakh", [None]),
    ("bill one lakh fifty", "one lakh", [None]),
    ("bill ek crore bees", "ek crore", [None]),
    ("Bill of five hundred thousand rupees from Ganesh.", "five hundred", [None]),
    ("Bill of five hundred thousand rupees from Ganesh.", "500", [None]),
    ("Bill of one hundred fifty thousand rupees.", "150", [None]),
    ("Bill of one hundred fifty thousand rupees.", "one hundred fifty", [None]),
    ("Bill paanch sau hazaar ka.", "paanch sau", [None]),
    # a bare number is not money; a second amount means the owner decides (batch 11 review, major; D29)
    ("Sharma ka bill dedh lakh rupaye, 5 November tak.", "5", [15_000_000]),
    ("Sharma ka bill dedh lakh rupaye, invoice 418.", "418", [15_000_000]),
    ("Do bill hain, dedh lakh ka.", "do", [15_000_000]),
    ("Sharma ka bill dedh lakh, advance pachaas hazaar diya tha.", "pachaas hazaar", [15_000_000, 5_000_000]),
    ("Sharma ka bill dedh lakh, advance pachaas hazaar diya tha.", "dedh lakh", [15_000_000, 5_000_000]),
    ("bill dedh lakh ka hai, 2 lakh nahi", "2 lakh", [15_000_000, 20_000_000]),
    ("bill 1,50,000 GST alag 27,000", "27,000", [15_000_000, 2_700_000]),
    ("bill no. 150, dedh lakh", "150", [15_000_000]),
    # no amount the code reads: never passed
    ("Sharma Packaging ka bill aaya hai, invoice 418, jaldi dena hai.", "dedh lakh", []),
    ("Bill aaya hai, amount baad mein bataunga.", "dedh lakh", []),
]


@pytest.mark.parametrize("transcript, spoken, said", FLAGGED)
def test_anything_but_the_one_amount_said_goes_to_the_owner(transcript, spoken, said):
    assert money_said(transcript) == said
    why = _flagged(transcript, spoken)
    if None in said:
        assert "an amount this app can't read in full" in why
    elif len(set(said)) > 1:
        assert "more than one amount" in why
    elif not said:
        assert "no amount this app can read" in why
    else:
        assert "is not the amount the voice note says" in why


@pytest.mark.parametrize("transcript, spoken, paise", [
    ("Ashirwad Paper ka bill, ek lakh pachaas hazaar rupaye.", "1,50,000", 15_000_000),
    ("Bill of Rs. 1,50,000 from Ashirwad Paper.", "ek lakh pachaas hazaar", 15_000_000),
    ("Ashirwad Paper ka bill, ek lakh aur pachaas hazaar rupaye.", "ek lakh pachaas hazaar", 15_000_000),
    ("Sharma ka bill, 1.5 lakh rupaye, paanch November tak.", "dedh lakh", 15_000_000),
    ("Sharma ka bill, pachaas hazaar rupaye, paanch November tak.", "pachaas hazaar", 5_000_000),
    ("Sharma ka bill dedh lakh rupaye... haan, dedh lakh, invoice 418.", "dedh lakh", 15_000_000),  # said twice
    ("₹1,50,000 ka bill hai, bill no. 150.", "1,50,000", 15_000_000),
])
def test_the_one_amount_said_passes_in_any_words(transcript, spoken, paise):
    checks, _, reading = _check(transcript, spoken)
    assert checks["amount"] == "passed" and reading["amount_paise"] == paise


def test_a_currency_word_or_a_sentence_end_ends_an_amount_and_a_comma_does_not():
    """"pachaas hazaar paanch" reads as ₹50,005, so the unit or a full stop after an amount must end it;
    a comma must not, or "ek lakh, pachaas hazaar" would be two amounts (batch 5, review round 2)."""
    assert money_said("Sharma ka bill, pachaas hazaar rupaye, paanch November tak.") == [5_000_000]
    assert money_said("Sharma ka bill pachaas hazaar. Paanch November tak.") == [5_000_000]
    assert money_said("Ashirwad ka bill, ek lakh, pachaas hazaar.") == [15_000_000]
    assert money_said("Rs. 1,50,000 only, 5 November tak") == [15_000_000]
    assert money_said("") == []


def test_the_known_false_flags_fail_safe():
    """D29's trade: with no unit or full stop after it, an amount runs into the next number word, and the
    owner types it. Never a wrong amount passed."""
    assert money_said("Sharma ka bill, 1.5 lakh, paanch November tak.") == [None]
    _flagged("Sharma ka bill, 1.5 lakh, paanch November tak.", "dedh lakh")
    assert money_said("Sharma ka bill pachaas hazaar paanch November tak") == [5_000_500]
    _flagged("Sharma ka bill pachaas hazaar paanch November tak", "pachaas hazaar")
