"""A currency word said after an amount is noise (batch 10, CHG-033, PO
D28). The live run's scenario 04, run 4 (docs/evals/raw-runs/2026-10-04-live-baseline),
gave amount_spoken "dedh lakh rup", the "rupaye" cut short, and the voice check
refused it. The number words decide the amount; a unit word at the end, or an
unambiguous start of one (three letters or more), is dropped. Anything else at
the end is still refused."""

import pytest

from app.ai.extract import VoiceBillExtract
from app.domain.money import parse_spoken_inr, without_currency_word
from app.validate.voice import check_voice
from tests.test_voice import NOTE


@pytest.mark.parametrize("said, paise", [
    ("dedh lakh rup", 15_000_000), ("dedh lakh rupaye", 15_000_000), ("dedh lakh rupees", 15_000_000),
    ("dedh lakh rupee", 15_000_000), ("dedh lakh rupiya", 15_000_000), ("dedh lakh Rs", 15_000_000),
    ("dedh lakh Rs.", 15_000_000), ("dedh lakh INR", 15_000_000), ("dedh lakh rupa", 15_000_000),
    ("45 hazaar rupe", 4_500_000), ("sawa do lakh rupai", 22_500_000), ("Dedh Lakh RUP", 15_000_000),
])
def test_a_currency_word_or_its_start_at_the_end_is_noise(said, paise):
    assert parse_spoken_inr(said) == paise


@pytest.mark.parametrize("said", [
    "dedh lakh ru",          # two letters: too short to be sure it is a unit
    "dedh lakh bhai",        # not a unit
    "dedh lakh rupx",        # not the start of a unit
    "dedh lakh rupaye bhai",  # the unit isn't at the end
    "dedh lakh rup2",
    "rupaye",                # no amount at all
])
def test_anything_else_at_the_end_is_still_refused(said):
    with pytest.raises(ValueError):
        parse_spoken_inr(said)


def test_only_the_trailing_unit_is_dropped():
    assert without_currency_word("dedh lakh rup") == "dedh lakh"
    assert without_currency_word("rupaye dedh lakh") == "rupaye dedh lakh"
    assert without_currency_word("dedh lakh bhai") == "dedh lakh bhai"


def test_the_voice_check_reads_the_live_runs_cut_short_unit():
    note = VoiceBillExtract.model_validate({**NOTE, "transcript": "Sharma Packaging ka bill, dedh lakh rupaye, "
                                                                  "paanch November tak dena hai.",
                                            "amount_spoken": "dedh lakh rup", "due_date": None})
    checks, _, reading = check_voice(note, None, lambda key: None)
    assert checks["amount"] == "passed" and reading["amount_paise"] == 15_000_000


def test_the_words_must_still_be_the_ones_said():
    note = VoiceBillExtract.model_validate({**NOTE, "transcript": "Sharma Packaging ka bill, do lakh rupaye.",
                                            "amount_spoken": "dedh lakh rup"})
    checks, _, _ = check_voice(note, None, lambda key: None)
    assert checks["amount"].startswith("failed")
