"""A day number next to a month name is a date, not money (CHG-042). Live
phase 2 caught it: Gemini writes scenario 04's note as "... dedh lakh rupaye
5 November tak dena hai", and batch 11's rule read the 5 after the unit as
more of the amount. D29 is unchanged: exactly one money-shaped amount, equal
in paise, and every earlier flagged form still flags."""

import pytest

from app.domain.money import money_said
from tests.test_voice_amount_said import _check, _flagged

LIVE = "Sharma Packaging ke bill dedh lakh rupaye 5 November tak dena hai."  # docs/evals, the live trace


@pytest.mark.parametrize("transcript", [
    LIVE,
    "Sharma Packaging ka bill, dedh lakh rupaye, paanch November tak dena hai.",
    "Sharma Packaging ka bill dedh lakh rupaye paanch November tak dena hai.",
    "Sharma Packaging ka bill dedh lakh rupaye 5th November tak dena hai.",
    "Sharma Packaging ka bill dedh lakh rupaye 5 Nov tak.",
    "Sharma Packaging ka bill dedh lakh rupaye 5 tarikh tak dena hai.",
    "Sharma Packaging ka bill dedh lakh, 5 November tak dena hai.",
    "Sharma Packaging ka bill dedh lakh. 5 November tak dena hai.",
    "Sharma Packaging ka bill 1,50,000 rupaye 5 November tak.",
])
def test_the_canonical_note_and_its_natural_transcriptions_pass(transcript):
    assert money_said(transcript) == [15_000_000]
    checks, _, reading = _check(transcript, "dedh lakh")
    assert checks["amount"] == "passed" and reading["amount_paise"] == 15_000_000


def test_a_day_before_a_month_ends_an_amount_and_is_never_money():
    assert money_said("Bill pachaas hazaar paanch November tak.") == [5_000_000]  # the guard: exactly one
    assert money_said("Bill pachaas hazaar. Paanch November tak.") == [5_000_000]
    assert money_said("Bill 1.5 lakh, paanch November tak.") == [15_000_000]
    assert money_said("Bill 5 November ko aaya, dedh lakh rupaye.") == [15_000_000]


@pytest.mark.parametrize("transcript, spoken, said", [
    ("Bill ek lakh rupaye pachaas November tak.", "ek lakh", [None]),  # 50 is no day: still more of the amount
    ("Bill ek lakh rupaye pachaas.", "ek lakh", [None]),
    ("Bill do lakh, advance pachaas hazaar diya, 5 November tak.", "do lakh", [20_000_000, 5_000_000]),
    ("Bill 25 to 30 lakh, 5 November tak.", "30 lakh", [None]),
])
def test_d29_still_holds_around_a_date(transcript, spoken, said):
    assert money_said(transcript) == said
    _flagged(transcript, spoken)
