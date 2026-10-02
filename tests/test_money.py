import pytest
from hypothesis import given, strategies as st

from app.domain.money import format_inr, parse_inr


@pytest.mark.parametrize(
    "paise, text",
    [
        (28_200_000, "₹2,82,000"),
        (18_300_000, "₹1,83,000"),
        (38_300_000, "₹3,83,000"),
        (6_700_000, "₹67,000"),
        (100_000, "₹1,000"),
        (10_000, "₹100"),
        (1_000_000_000, "₹1,00,00,000"),
        (0, "₹0"),
        (5_050, "₹50.50"),
        (1, "₹0.01"),
        (-6_700_000, "-₹67,000"),
    ],
)
def test_format_inr_uses_indian_lakh_grouping(paise, text):
    assert format_inr(paise) == text


@pytest.mark.parametrize("bad", [1800.0, True, False, "1800", None])
def test_format_inr_refuses_anything_but_int(bad):
    with pytest.raises(TypeError):
        format_inr(bad)


@given(st.integers(min_value=-(10**13), max_value=10**13))
def test_format_inr_round_trips(paise):
    text = format_inr(paise)
    negative = text.startswith("-")
    digits = text.lstrip("-").removeprefix("₹").replace(",", "")
    rupees, _, frac = digits.partition(".")
    value = int(rupees) * 100 + (int(frac) if frac else 0)
    assert (-value if negative else value) == paise


# --- parse_inr (batch 2 plan, Q4; CHG-004 AC10) ----------------------------------


@pytest.mark.parametrize("text, paise", [
    ("Rs.1,20,000.00", 12_000_000),
    ("INR 120000", 12_000_000),
    ("₹ 1,20,000", 12_000_000),
    ("₹1,20,000", 12_000_000),
    ("Rs 1,80,000", 18_000_000),
    ("Rs. 45,000/-", 4_500_000),
    ("INR 33,000.00", 3_300_000),
    ("₹45,000.5", 4_500_050),
    ("Rs.0.75", 75),
    ("1,200,000", 120_000_000),       # western grouping: commas are only separators
    ("12,34,56,789.10", 123_456_789_10),
    ("  INR 500  ", 50_000),
    ("₹0", 0),
])
def test_parse_inr_reads_the_forms_bank_alerts_use(text, paise):
    assert parse_inr(text) == paise


@pytest.mark.parametrize("text", [
    "1.2 lakh", "1.2 Lakh", "12 lakhs", "1 crore", "45k",          # words: never guessed
    "-1,20,000", "Rs.-500", "-₹500", "(500)", "+500",              # signs
    "18O000", "1,2O,000", "Rs.l,000",                              # letters for digits
    "1,20,00", "12,0000", "1,,000", ",500", "500,",                # broken grouping
    "500.123", "500.", ".50", "5.00.00",                           # broken decimals
    "", "   ", "Rs.", "INR", "₹", "USD 500", "$500", "500 INR",    # no amount / other money
    "Rs.1,20,000 and Rs.5,000", "1 20 000",                        # more than one number
])
def test_parse_inr_refuses_anything_else(text):
    with pytest.raises(ValueError):
        parse_inr(text)


@pytest.mark.parametrize("bad", [120000, 1200.0, None, b"500"])
def test_parse_inr_takes_only_text(bad):
    with pytest.raises(TypeError):
        parse_inr(bad)


@given(st.integers(min_value=0, max_value=10**13))
def test_parse_inr_reads_back_what_format_inr_writes(paise):
    assert parse_inr(format_inr(paise)) == paise


@given(st.integers(min_value=1, max_value=10**13))
def test_parse_inr_refuses_every_negative_format_inr_writes(paise):
    with pytest.raises(ValueError):
        parse_inr(format_inr(-paise))
