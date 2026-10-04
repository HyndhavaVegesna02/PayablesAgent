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
    # a number word the parser doesn't read is still part of the amount (batch 11 review, round 2)
    ("Sharma ka bill ek lakh dus hazaar rupaye.", "ek lakh", [None]),
    ("Sharma ka bill ek lakh baees hazaar.", "1,00,000", [None]),
    ("Sharma ka bill ek lakh baees hazaar.", "ek lakh", [None]),
    ("Sharma ka bill do lakh pachpan hazaar rupaye.", "do lakh", [None]),
    ("Sharma ka bill teen lakh chaubees hazaar ka.", "teen lakh", [None]),
    ("Bill ek lakh pachhattar hazaar.", "ek lakh", [None]),
    ("bill do lakh ikkis hazaar", "do lakh", [None]),
    ("bill one lakh twenty-five", "one lakh", [None]),
    ("Sharma ka bill sava do lakh.", "do lakh", [None]),
    ("Bill saare teen lakh.", "teen lakh", [None]),
    ("Sharma ka bill ek laakh pachaas hazaar.", "pachaas hazaar", [None]),
    ("Bill of a hundred and fifty thousand rupees.", "fifty thousand", [None]),
    ("Bill minus pachaas hazaar.", "pachaas hazaar", [None]),
    ("Teen sau bori aayi, baees hazaar ka bill.", "teen sau", [30_000, None]),
    # a number after the unit or the sentence that closed an amount belongs to it (round 2)
    ("Bill ek lakh. Pachaas.", "ek lakh", [None]),
    ("Bill ek lakh; pachaas", "ek lakh", [None]),
    ("bill ek lakh rupaye pachaas", "ek lakh", [None]),
    ("bill dedh lakh rup pachaas", "dedh lakh", [None]),
    ("bill ek lakh rupaye pachaas paise", "ek lakh", [None, None]),
    ("bill ek lakh rupaye aur pachaas hazaar", "ek lakh", [None, 5_000_000]),
    # an amount written as one token, with marks, is still an amount (batch 11 review, round 3)
    ("Rs. 1,50,000/- ka bill, advance 50,000 diya.", "50,000", [15_000_000, 5_000_000]),
    ("Bill 1,50,000/- only, advance 50,000 diya.", "50,000", [15_000_000, 5_000_000]),
    ("Rs1,50,000 ka bill, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("INR1,50,000 ka bill, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill 1,50,000rs, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill 1,50,000-, advance 50,000 diya.", "50,000", [15_000_000, 5_000_000]),
    ("Bill 1.5L ka, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill 150k ka, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill 2cr ka, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill Rs 2.5 cr ka.", "2.5", [None]),
    ("Bill Rs 50 k ka.", "50", [None]),
    ("Bill Rs 1.5 L ka.", "1.5", [None]),
    ("Bill ₹50 k ka.", "₹50", [None]),
    # a number straight after digits is more of that amount, unread (round 3)
    ("Bill Rs 1,00,000 pachaas.", "1,00,000", [None]),
    ("Bill 1,50,000 pachaas.", "1,50,000", [None]),
    ("Bill Rs 1,00,000 dus.", "1,00,000", [None]),
    ("Bill Rs 100000 50000.", "100000", [None, 5_000_000]),  # D30: 50000 is money too
    ("Bill Rs 1,00,000 50000.", "1,00,000", [None, 5_000_000]),
    ("Bill Rs 1,50,000 50 paise.", "1,50,000", [None, None]),
    ("Bill Rs 1,50,000 aur 50 paise.", "1,50,000", [None, None]),
    # a range or a guess is no one amount (round 3)
    ("Bill 25 - 30 lakh", "30 lakh", [None]),
    ("Bill 25 to 30 lakh", "30 lakh", [None]),
    ("Bill 25 ya 30 lakh", "30 lakh", [None]),
    ("Bill 25 or 30 lakh", "30 lakh", [None]),
    ("Bill lagbhag do lakh", "do lakh", [None]),
    ("Bill do lakh se zyada", "do lakh", [None]),
    ("Bill ek lakh plus GST.", "ek lakh", [None]),
    # a hyphenated amount is an amount (round 3)
    ("Teen sau bori, dedh-lakh ka bill.", "teen sau", [30_000, 15_000_000]),
    ("Teen sau bori, ek lakh-ish ka bill.", "teen sau", [30_000, None]),
    ("Bill ek_lakh pachaas hazaar", "pachaas hazaar", [15_000_000]),
    # any word with a digit in it is a number; letters or marks on it make it money (round 4)
    ("Bill 1,50,000rupaye ka, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill 1,50,000rupees, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Rs 1,50,000/= ka bill, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill 1,50,000/ ka, advance 50,000 diya.", "50,000", [15_000_000, 5_000_000]),
    ("Bill 50hazaar ka, advance 20,000 diya.", "20,000", [None, 2_000_000]),
    ("Bill 1,50,000x2 ka, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill 2x75,000 ka, advance 50,000.", "50,000", [None, 5_000_000]),
    ("Credit note -1,50,000, bill 50,000 ka.", "50,000", [None, 5_000_000]),
    ("Bill 150000= ka, advance 50,000 diya.", "50,000", [None, 5_000_000]),
    ("Bill ₹-1,50,000 hai.", "1,50,000", [None]),
    # a guess after the unit or the full stop that closed an amount (round 4)
    ("Bill do lakh rupaye se zyada.", "do lakh", [None]),
    ("Bill dedh lakh rupees approx.", "dedh lakh", [None]),
    ("Bill ek lakh rupees plus GST.", "ek lakh", [None]),
    ("Bill ek lakh rupaye ke upar.", "ek lakh", [None]),
    ("Bill ek lakh. Plus GST.", "ek lakh", [None]),
    ("Bill ek lakh + GST.", "ek lakh", [None]),
    ("Bill ₹1,00,000 + GST.", "1,00,000", [None]),
    ("Bill 1,00,000 + 18% GST.", "1,00,000", [None]),
    # a written amount after a comma is its own (round 4)
    ("Bill do lakh, 50,000 advance diya.", "do lakh", [20_000_000, 5_000_000]),
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
    ("Rupees one lakh fifty thousand only, due on 5 November.", "one lakh fifty thousand", 15_000_000),
    ("Sharma ka bill, do lakh 21 hazaar rupaye, 2026-11-05 tak.", "2,21,000", 22_100_000),
    ("Bill no. 150, dedh lakh rupaye, dus din mein.", "dedh lakh", 15_000_000),
    ("Rs. 1,50,000/- ka bill hai.", "1,50,000", 15_000_000),
    ("Bill dedh-lakh ka.", "dedh lakh", 15_000_000),
    ("Bill ek-lakh-pachaas-hazaar ka.", "1,50,000", 15_000_000),
    ("Rs 1,50,000, 5 November tak.", "1,50,000", 15_000_000),
    ("Sharma ji ke paise dene hain, dedh lakh rupaye.", "dedh lakh", 15_000_000),  # paise as money in general
    ("Dedh lakh rupaye ka bill, due 5.11.2026.", "dedh lakh", 15_000_000),
    ("Dedh lakh rupaye de-do Sharma ji ko.", "dedh lakh", 15_000_000),
    ("Bill 1,50,000/- hai, invoice AP/2610/150, 5th November tak.", "1,50,000", 15_000_000),
    ("Sharma ka bill dedh lakh rupaye to dena hai.", "dedh lakh", 15_000_000),  # "to": "so", after the unit
])
def test_the_one_amount_said_passes_in_any_words(transcript, spoken, paise):
    checks, _, reading = _check(transcript, spoken)
    assert checks["amount"] == "passed" and reading["amount_paise"] == paise


def test_a_currency_word_or_a_sentence_end_ends_an_amount_and_a_comma_does_not():
    """"pachaas hazaar paanch" reads as ₹50,005, so the unit or a full stop after an amount must end it;
    a comma must not, or "ek lakh, pachaas hazaar" would be two amounts (batch 5, review round 2)."""
    assert money_said("Sharma ka bill, pachaas hazaar rupaye, paanch November tak.") == [5_000_000]
    assert money_said("Sharma ka bill pachaas hazaar. Kal tak.") == [5_000_000]
    assert money_said("Ashirwad ka bill, ek lakh, pachaas hazaar.") == [15_000_000]
    assert money_said("Rs. 1,50,000 only, 5 November tak") == [15_000_000]
    assert money_said("") == []


def test_what_code_cannot_tell_by_form_is_left_to_the_owner():
    """Left for the PO (review.md, round 2-3): a word between ends an amount, so a tail after it is a bare
    number, and an amount that isn't the total by meaning passes. The owner confirms every voice bill with
    the transcript beside it."""
    assert money_said("Bill ek lakh hai, pachaas.") == [10_000_000]
    assert money_said("Bill ek lakh rupaye, pachaas.") == [10_000_000]
    assert money_said("Baaki dedh lakh baad mein dena hai.") == [15_000_000]


def test_the_known_false_flags_fail_safe():
    """D29's trade: with no unit or full stop after it, an amount runs into the next number word; and a
    number word just after a full stop may be more of the amount before it. The owner types it. Never a
    wrong amount passed. (A day before a month name is a date since CHG-042; without the month, it isn't.)"""
    assert money_said("Sharma ka bill pachaas hazaar. Paanch ko dena hai.") == [None]
    _flagged("Sharma ka bill pachaas hazaar. Paanch ko dena hai.", "pachaas hazaar")
    assert money_said("Sharma ka bill, 1.5 lakh, paanch ko dena hai.") == [None]
    _flagged("Sharma ka bill, 1.5 lakh, paanch ko dena hai.", "dedh lakh")
    assert money_said("Sharma ka bill pachaas hazaar paanch ko dena hai") == [5_000_500]
    _flagged("Sharma ka bill pachaas hazaar paanch ko dena hai", "pachaas hazaar")
