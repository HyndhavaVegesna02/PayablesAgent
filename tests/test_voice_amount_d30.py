"""The voice amount check's last rules (CHG-039; PO D30). A bare run of five
or more digits is money, so a bill written bare and an advance written
grouped are two amounts; a Unicode minus, a sign after a rupee word, and a
spaced "/", "--" or "&" between numbers read like their plain forms. Each
can only send a bill to the owner."""

import pytest

from app.domain.money import money_said, parse_spoken_inr
from tests.test_voice_amount_said import _check, _flagged


@pytest.mark.parametrize("transcript, spoken, said", [
    # D30: bare 5+ digits are money
    ("Bill 150000 ka, advance 50,000 diya.", "50,000", [15_000_000, 5_000_000]),
    ("Sharma ka bill 150000 hai, advance 20,000.", "20,000", [15_000_000, 2_000_000]),
    ("Bill 50000 ka, advance 20000 diya.", "20000", [5_000_000, 2_000_000]),
    # a Unicode minus is a minus
    ("Bill −1,50,000 ka.", "1,50,000", [None]),
    ("Credit note −50,000, bill dedh lakh rupaye.", "dedh lakh", [None, 15_000_000]),
    # spaced range punctuation is a range
    ("Bill 25 / 30 lakh", "30 lakh", [None]),
    ("Bill 25 -- 30 lakh", "30 lakh", [None]),
    ("Bill 25 & 30 lakh", "30 lakh", [None]),
    ("Bill 25 − 30 lakh", "30 lakh", [None]),
    # a minus inside an amount, or a mark after a scale word, never adds or drops (batch 12 review, critical)
    ("Bill do lakh −50,000 advance.", "2,50,000", [None]),
    ("Bill do lakh −50,000 advance.", "dhai lakh", [None]),
    ("Bill 2 lakh −50,000 advance.", "2,50,000", [None]),
    ("Bill do lakh -50,000 advance.", "2,50,000", [None]),
    ("Bill do lakh -50 hazaar.", "dhai lakh", [None]),
    ("Bill do lakh−50 hazaar.", "dhai lakh", [None]),
    ("Bill do lakh− advance 50,000.", "50,000", [20_000_000, 5_000_000]),
    ("Bill do lakh−, advance 50,000.", "50,000", [20_000_000, 5_000_000]),
    ("Bill do lakh- advance 50,000.", "50,000", [20_000_000, 5_000_000]),
])
def test_d30_and_the_last_forms_go_to_the_owner(transcript, spoken, said):
    assert money_said(transcript) == said
    _flagged(transcript, spoken)


@pytest.mark.parametrize("said", ["rupees -5", "Rupaye -1,50,000", "Rs.-5", "₹ -5", "rs -150000", "INR −5"])
def test_a_sign_after_a_currency_word_is_still_a_negative_amount(said):
    with pytest.raises(ValueError, match="negative"):
        parse_spoken_inr(said)


@pytest.mark.parametrize("transcript, spoken, paise", [
    ("Bill 150000 ka hai.", "1,50,000", 15_000_000),  # bare digits, now money, are the one amount
    ("Dedh lakh rupaye ka bill, 2026 mein dena hai, invoice 4182.", "dedh lakh", 15_000_000),  # a year is not
    ("Sharma & Sons ka bill, dedh lakh rupaye.", "dedh lakh", 15_000_000),  # "&" between words, not numbers
])
def test_bare_digits_alone_are_the_amount_and_a_year_stays_bare(transcript, spoken, paise):
    checks, _, reading = _check(transcript, spoken)
    assert checks["amount"] == "passed" and reading["amount_paise"] == paise


def test_a_long_invoice_number_is_the_accepted_false_flag():
    """D30's trade: five or more bare digits are money, so a long invoice number beside the amount is a
    second amount, and the owner types it."""
    assert money_said("Invoice 418277, dedh lakh rupaye.") == [41_827_700, 15_000_000]
    _flagged("Invoice 418277, dedh lakh rupaye.", "dedh lakh")
