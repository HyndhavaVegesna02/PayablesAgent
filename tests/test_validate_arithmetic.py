"""Invoice and statement arithmetic (batch 5 plan, S1; PO decision D19):
exact to the paise, with one allowance, an explicit round-off line of at most
₹1.00."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.validate import NOT_APPLICABLE, PASSED
from app.validate.arithmetic import check_invoice_arithmetic, check_statement_arithmetic

# Two items, 9% CGST + 9% SGST: 1,00,000 + 52,540.68 = 1,52,540.68; GST 27,457.32 each half
LINES = [10_000_000, 5_254_068]
GST = [1_372_866, 1_372_866]
EXACT = sum(LINES) + sum(GST)  # 1,79,99,866 paise: ₹1,79,998.66


def test_an_exact_invoice_passes():
    assert check_invoice_arithmetic(LINES, GST, EXACT) == PASSED


@pytest.mark.parametrize("round_off", [40, -40])
def test_d19_a_printed_round_off_of_forty_paise_passes(round_off):
    assert check_invoice_arithmetic(LINES, GST, EXACT + round_off, round_off=round_off) == PASSED


def test_d19_a_round_off_of_one_rupee_fifty_fails():
    assert check_invoice_arithmetic(LINES, GST, EXACT + 150, round_off=150) == (
        "failed: the round-off of ₹1.50 is more than ₹1"
    )


def test_d19_an_implicit_mismatch_with_no_round_off_line_fails():
    assert check_invoice_arithmetic(LINES, GST, EXACT + 34) == (
        "failed: items ₹1,52,540.68 + GST ₹27,457.32 = ₹1,79,998, but the total is ₹1,79,998.34"
    )


def test_a_round_off_line_must_still_make_the_sum_exact():
    assert check_invoice_arithmetic(LINES, GST, EXACT + 40, round_off=-40).startswith("failed: items")


def test_an_invoice_with_no_item_lines_is_not_applicable():
    assert check_invoice_arithmetic([], [], EXACT) == NOT_APPLICABLE


def test_a_float_amount_is_refused_outright():
    with pytest.raises(TypeError):
        check_invoice_arithmetic([100.0], [], 100)  # type: ignore[list-item]


amounts = st.lists(st.integers(1, 10**10), min_size=1, max_size=8)


@given(amounts, st.lists(st.integers(0, 10**9), max_size=3), st.integers(-100, 100))
def test_any_exact_invoice_within_the_allowance_passes(lines, gst, round_off):
    assert check_invoice_arithmetic(lines, gst, sum(lines) + sum(gst) + round_off, round_off=round_off) == PASSED


@given(amounts, st.integers(1, 10**6))
def test_any_unexplained_difference_fails(lines, off):
    assert check_invoice_arithmetic(lines, [], sum(lines) + off).startswith("failed: ")


def test_a_statement_that_adds_up_passes():
    assert check_statement_arithmetic(44_000_000, [26_000_000], [18_000_000, 3_200_000], 48_800_000) == PASSED


def test_a_statement_that_does_not_add_up_fails_with_the_sums():
    assert check_statement_arithmetic(44_000_000, [26_000_000], [18_000_000], 50_000_000) == (
        "failed: opening ₹4,40,000 + credits ₹2,60,000 - debits ₹1,80,000 = ₹5,20,000, "
        "but the closing balance is ₹5,00,000"
    )


def test_a_statement_with_no_rows_keeps_its_balance():
    assert check_statement_arithmetic(100, [], [], 100) == PASSED


@pytest.mark.parametrize("opening, closing, missing", [(None, 1, "opening"), (1, None, "closing")])
def test_an_unreadable_statement_balance_fails(opening, closing, missing):
    assert check_statement_arithmetic(opening, [], [], closing) == (
        f"failed: the statement's {missing} balance could not be read"
    )
