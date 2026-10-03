"""The GSTIN check (batch 5 plan, S1): format plus GSTN's mod-36 check
character, tested against an independent vector (the GST portal's published
sample) rather than only values our own code produced."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.validate import NOT_APPLICABLE, PASSED
from app.validate.gstin import ALPHABET, check_character, check_gstin, normalise_gstin

# Published samples, independent of this code: the GST portal's example GSTIN,
# and a second sample widely quoted in GST documentation.
PUBLISHED = ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4"]

# Fictional GSTINs for the fixtures (batch 5, PO requirement). The PAN part starts
# "ZZZ", which no real PAN series uses for these businesses, and the check
# character is computed by check_character, itself pinned by PUBLISHED above.
FICTIONAL = {
    "Ashirwad Paper Suppliers": "27ZZZFZ0001Z1ZU",
    "Kaveri Traders": "29ZZZCZ0002Z1ZV",
    "Prime Chem Industries": "24ZZZPZ0003Z1ZD",
    "Saraswati Precision Works (the business)": "27ZZZCZ0004Z1ZX",
}


@pytest.mark.parametrize("gstin", PUBLISHED)
def test_published_samples_pass(gstin):
    assert check_gstin(gstin) == PASSED


@pytest.mark.parametrize("gstin", FICTIONAL.values())
def test_fictional_fixture_gstins_are_valid(gstin):
    assert check_gstin(gstin) == PASSED


def test_a_wrong_check_character_names_the_right_one():
    assert check_gstin("27AAPFU0939F1ZA") == "failed: 27AAPFU0939F1ZA: check character should be V"


def test_written_with_spaces_and_lower_case_is_read_the_same():
    assert normalise_gstin(" 27aapfu 0939f1zv ") == "27AAPFU0939F1ZV"
    assert check_gstin(" 27aapfu 0939f1zv ") == PASSED


@pytest.mark.parametrize("bad", ["27AAPFU0939F1Z", "27AAPFU0939F1ZVV", "2AAAPFU0939F1ZV", "27AAPF10939F1ZV",
                                 "27AAPFU0939F0ZV", "27AAPFU0939F1YV"])
def test_a_malformed_gstin_fails_on_format(bad):
    assert check_gstin(bad).startswith("failed: ") and "is not a GSTIN" in check_gstin(bad)


def test_absent_is_not_applicable_unless_the_document_shows_registration():
    assert check_gstin(None) == NOT_APPLICABLE
    assert check_gstin("  ") == NOT_APPLICABLE
    assert check_gstin(None, required=True) == "failed: the GSTIN could not be read"


gstins = st.builds(
    lambda state, pan_l, pan_d, last, entity: (f"{state:02d}{pan_l}{pan_d}{last}{entity}Z"),
    st.integers(1, 38), st.text("ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=5, max_size=5),
    st.text("0123456789", min_size=4, max_size=4), st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    st.sampled_from("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
).map(lambda first14: first14 + check_character(first14))


@given(gstins)
def test_any_built_gstin_passes(g):
    assert check_gstin(g) == PASSED


@given(gstins, st.integers(0, 14), st.sampled_from(ALPHABET))
def test_any_single_character_change_fails(g, at, ch):
    changed = g[:at] + ch + g[at + 1:]
    if changed != g:
        assert check_gstin(changed).startswith("failed: ")
