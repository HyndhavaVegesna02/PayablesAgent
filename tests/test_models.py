from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.models import BankTxnNew, Payable, PayableNew, ReceivableNew, TaxObligationNew


def _payable(**over):
    base = dict(
        business_id=1, amount_paise=18_000_000, due_date=date(2026, 10, 14), priority="normal"
    )
    return PayableNew(**{**base, **over})


def test_payable_new_accepts_int_paise():
    assert _payable().amount_paise == 18_000_000


@pytest.mark.parametrize("bad", [1800.0, 18_000_000.0, True, "18000000"])
def test_money_fields_refuse_non_int(bad):
    with pytest.raises(ValidationError):
        _payable(amount_paise=bad)


@pytest.mark.parametrize("bad", [0, -1])
def test_amounts_must_be_positive(bad):
    with pytest.raises(ValidationError):
        _payable(amount_paise=bad)


@pytest.mark.parametrize(
    "discount, by",
    [(18_000_000, date(2026, 10, 12)), (19_000_000, date(2026, 10, 12)),
     (100, None), (None, date(2026, 10, 12))],
)
def test_discount_must_be_smaller_than_the_bill_and_dated(discount, by):
    with pytest.raises(ValidationError):
        _payable(discount_paise=discount, discount_by=by)


def test_a_valid_discount_is_accepted():
    p = _payable(discount_paise=200_000, discount_by=date(2026, 10, 12))
    assert p.discount_paise == 200_000


def test_unknown_priority_refused():
    with pytest.raises(ValidationError):
        _payable(priority="urgent")


def test_unknown_field_refused():
    with pytest.raises(ValidationError):
        _payable(status="PAID")


def test_payable_row_model_parses_a_db_row_shape():
    row = dict(
        id=3, business_id=1, party_id=None, invoice_number="X", invoice_date=None,
        amount_paise=100, due_date="2026-10-14", priority="normal", grace_days=0,
        discount_paise=None, discount_by=None, parent_payable_id=None,
        source_document_id=None, status="CONFIRMED", planned_date=None,
        approved_by=None, approved_at=None, matched_txn_id=None, version=2,
    )
    p = Payable.model_validate(row)
    assert p.due_date == date(2026, 10, 14)
    assert p.version == 2


def test_receivable_cannot_be_created_confirmed():
    with pytest.raises(ValidationError):
        ReceivableNew(business_id=1, amount_paise=100, confidence="CONFIRMED")


def test_bank_txn_new_only_unmatched_or_adjustment():
    base = dict(account_id=1, direction="debit", amount_paise=100, txn_date=date(2026, 10, 12), dedup_key="k")
    assert BankTxnNew(**base, status="UNMATCHED").status == "UNMATCHED"
    with pytest.raises(ValidationError):
        BankTxnNew(**base, status="MATCHED")


def test_tax_amount_required_unless_missing():
    base = dict(business_id=1, tax_type="GST", period="2026-09", due_date=date(2026, 10, 20))
    assert TaxObligationNew(**base, amount_paise=None, amount_status="MISSING").amount_paise is None
    with pytest.raises(ValidationError):
        TaxObligationNew(**base, amount_paise=None, amount_status="ESTIMATED")
    with pytest.raises(ValidationError):
        TaxObligationNew(**base, amount_paise=100, amount_status="MISSING")
