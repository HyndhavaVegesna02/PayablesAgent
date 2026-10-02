import pytest
from hypothesis import given, strategies as st

from app.domain.money import format_inr


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
