"""The voice amount check compares numbers, not text (CHG-037, PO's batch 10
verdict). The paise code reads from the model's amount_spoken must equal, as
an integer, an amount code reads from the transcript, each read in full: the
words of a leading part of what was said ("do lakh" of "do lakh pachaas
hazaar") are a different amount, and the owner types it."""

import pytest

from app.ai.extract import VoiceBillExtract
from app.domain.money import amounts_said
from app.validate.voice import check_voice
from tests.test_voice import NOTE


def _check(transcript, spoken):
    note = VoiceBillExtract.model_validate({**NOTE, "transcript": transcript, "amount_spoken": spoken})
    return check_voice(note, None, lambda key: None)


@pytest.mark.parametrize("transcript, spoken", [
    ("Sharma Packaging ka bill, dedh lakh pachaas hazaar rupaye, 5 November tak.", "dedh lakh"),
    ("Ashirwad Paper ka bill hai do lakh pachaas hazaar ka, invoice AP/2610/150.", "do lakh"),
    ("Kumar ji, bees hazaar paanch sau rupaye, kal tak dena hai.", "bees hazaar"),
    ("Total ek lakh pachaas hazaar rupees.", "ek lakh"),
    ("Bill of 1,50,500 rupees from Ganesh Hardware.", "1,50,000"),
])
def test_part_of_what_was_said_is_another_amount_and_goes_to_the_owner(transcript, spoken):
    checks, record, reading = _check(transcript, spoken)
    assert checks["amount"].startswith("failed") and "not an amount said" in checks["amount"]
    assert record is None and reading["amount_paise"] is None  # the owner types it, beside the transcript


@pytest.mark.parametrize("transcript", [
    "Sharma Packaging ka bill aaya hai, invoice 418, jaldi dena hai.",
    "Bill aaya hai, amount baad mein bataunga.",
])
def test_a_transcript_with_no_amount_code_reads_never_passes(transcript):
    assert amounts_said(transcript) in ([], [41_800])  # "418" is the invoice number, read as a number
    checks, record, reading = _check(transcript, "dedh lakh")
    assert checks["amount"].startswith("failed") and "not an amount said" in checks["amount"]
    assert record is None and reading["amount_paise"] is None


@pytest.mark.parametrize("transcript, spoken, paise", [
    ("Ashirwad Paper ka bill, ek lakh pachaas hazaar rupaye.", "1,50,000", 15_000_000),
    ("Bill of Rs. 1,50,000 from Ashirwad Paper.", "ek lakh pachaas hazaar", 15_000_000),
    ("Ashirwad Paper ka bill, ek lakh aur pachaas hazaar rupaye.", "ek lakh pachaas hazaar", 15_000_000),
    ("Sharma ka bill, 1.5 lakh, paanch November tak.", "dedh lakh", 15_000_000),
])
def test_the_same_amount_in_other_words_passes(transcript, spoken, paise):
    checks, _, reading = _check(transcript, spoken)
    assert checks["amount"] == "passed" and reading["amount_paise"] == paise


def test_a_currency_word_or_a_sentence_end_ends_an_amount_and_a_comma_does_not():
    """"pachaas hazaar paanch" reads as ₹50,005, so the unit or a full stop after an amount must end it;
    a comma must not, or "ek lakh, pachaas hazaar" would be two amounts (batch 5, review round 2)."""
    assert amounts_said("Sharma ka bill, pachaas hazaar rupaye, paanch November tak.") == [5_000_000, 500]
    assert amounts_said("Sharma ka bill pachaas hazaar. Paanch November tak.") == [5_000_000, 500]
    assert amounts_said("Ashirwad ka bill, ek lakh, pachaas hazaar.") == [15_000_000]
    checks, _, reading = _check("Sharma ka bill, pachaas hazaar rupaye, paanch November tak.", "pachaas hazaar")
    assert checks["amount"] == "passed" and reading["amount_paise"] == 5_000_000


def test_amounts_said_reads_each_amount_in_full():
    assert amounts_said("Do bill hain: pehla dedh lakh pachaas hazaar, doosra bees hazaar paanch sau.") == [
        200, 20_000_000, 2_050_000]  # "do" (two bills) is a number too; the check needs an equal one
    assert amounts_said("Rs. 1,50,000 only, 5 November tak") == [15_000_000, 500]
    assert amounts_said("") == []
