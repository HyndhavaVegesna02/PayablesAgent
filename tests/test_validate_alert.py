"""Rule checks for alerts and failure notices (batch 2 plan, CHG-004 AC4, AC5
and AC10): every Part 1 check is recorded, amounts come from parse_inr, and a
failure says why."""

from datetime import date, datetime, timezone

import pytest

from app.ai.extract import BankAlertExtract, FailureNoticeExtract
from app.clock import TIMEZONE
from app.validate import CHECK_NAMES, failures
from app.validate.alert import AccountIn, MailFacts, check_bank_alert, check_failure_notice
from app.validate.duplicates import txn_dedup_key

BANK = "alerts@hdfcbank.example"
ACCOUNTS = [AccountIn(1, "4821", frozenset({BANK})), AccountIn(2, "7730", frozenset())]
MAIL = MailFacts(BANK, datetime(2026, 10, 12, 11, 42, tzinfo=TIMEZONE))
NO_DUPES = lambda key: None  # noqa: E731


def alert(**over):
    base = dict(account_last4="4821", direction="debit", amount_text="Rs.1,80,000.00",
                txn_date=date(2026, 10, 12), counterparty="ASHIRWAD PAPER SUPPLIERS",
                reference="N 2862 6123 4567", available_balance_text="Rs.4,40,000.00",
                uncertain_fields=[])
    return BankAlertExtract(**{**base, **over})


def notice(**over):
    base = dict(account_last4="4821", amount_text="Rs.1,80,000.00", original_reference="N286261234567",
                failure_date=date(2026, 10, 12), reason="Beneficiary account closed", uncertain_fields=[])
    return FailureNoticeExtract(**{**base, **over})


def test_a_good_alert_passes_every_check_and_becomes_a_record():
    checks, rec = check_bank_alert(alert(), None, MAIL, ACCOUNTS, NO_DUPES)
    assert list(checks) == list(CHECK_NAMES)
    assert checks == {
        "schema": "passed", "amount": "passed", "balance": "passed", "account": "passed",
        "dates": "passed", "duplicates": "passed", "confidence": "passed",
        "gstin": "not_applicable", "invoice_arithmetic": "not_applicable",
        "statement_arithmetic": "not_applicable",
    }
    assert (rec.account_id, rec.direction, rec.amount_paise, rec.balance_after_paise) == (
        1, "debit", 18_000_000, 44_000_000,
    )
    assert rec.reference == "N286261234567"  # spaces dropped, upper-cased
    assert rec.dedup_key == txn_dedup_key(1, date(2026, 10, 12), "debit", 18_000_000, "N286261234567")
    assert rec.dedup_key == "1:2026-10-12:debit:18000000:N286261234567"


def test_no_balance_in_the_alert_is_not_applicable():
    checks, rec = check_bank_alert(alert(available_balance_text=None), None, MAIL, ACCOUNTS, NO_DUPES)
    assert checks["balance"] == "not_applicable"
    assert rec.balance_after_paise is None


@pytest.mark.parametrize("over, check, why", [
    ({"amount_text": "1.8 lakh"}, "amount", "not an amount in rupees"),
    ({"amount_text": "Rs.-1,80,000"}, "amount", "not an amount in rupees"),
    ({"amount_text": "Rs.0.00"}, "amount", "not more than zero"),
    ({"amount_text": ""}, "amount", "not an amount in rupees"),
    ({"available_balance_text": "Rs.4.4 lakh"}, "balance", "available balance"),
    ({"account_last4": "9999"}, "account", "no account of this business ends in 9999"),
    ({"account_last4": "7730"}, "account", "is not an alert sender for the account ending 7730"),
    ({"txn_date": date(2026, 10, 13)}, "dates", "after the email was sent"),
    ({"txn_date": date(2026, 10, 4)}, "dates", "more than 7 days before"),
    ({"uncertain_fields": ["reference", "amount_text"]}, "confidence", "unsure of amount_text, reference"),
])
def test_each_failed_check_says_why_and_blocks_the_record(over, check, why):
    checks, rec = check_bank_alert(alert(**over), None, MAIL, ACCOUNTS, NO_DUPES)
    assert rec is None
    assert check in failures(checks)
    assert why in failures(checks)[check]


def test_seven_days_before_the_email_is_still_allowed():
    checks, _ = check_bank_alert(alert(txn_date=date(2026, 10, 5)), None, MAIL, ACCOUNTS, NO_DUPES)
    assert checks["dates"] == "passed"


def test_an_unknown_sender_fails_the_account_check():
    other = MailFacts("phish@hdfcbank-alerts.example", MAIL.sent_at)
    checks, rec = check_bank_alert(alert(), None, other, ACCOUNTS, NO_DUPES)
    assert "account" in failures(checks) and rec is None


def test_an_email_with_no_date_fails_the_dates_check():
    checks, _ = check_bank_alert(alert(), None, MailFacts(BANK, None), ACCOUNTS, NO_DUPES)
    assert failures(checks)["dates"] == "the email has no readable Date header"


def test_a_duplicate_names_the_transaction_it_repeats():
    seen = {}

    def lookup(key):
        seen["key"] = key
        return 41

    checks, rec = check_bank_alert(alert(), None, MAIL, ACCOUNTS, lookup)
    assert failures(checks) == {"duplicates": "same as bank transaction 41"}
    assert rec is None
    assert seen["key"] == "1:2026-10-12:debit:18000000:N286261234567"


def test_a_reply_that_failed_the_schema_records_every_check_without_running_them():
    checks, rec = check_bank_alert(None, "amount_text: Field required", MAIL, ACCOUNTS, NO_DUPES)
    assert list(checks) == list(CHECK_NAMES)
    assert checks["schema"] == "failed: amount_text: Field required"
    assert checks["amount"].startswith("skipped:")
    assert checks["gstin"] == "not_applicable"
    assert rec is None


def test_a_failure_notice_passes_and_becomes_a_record():
    checks, rec = check_failure_notice(notice(), None, MAIL, ACCOUNTS, NO_DUPES)
    assert list(checks) == list(CHECK_NAMES)
    assert checks["balance"] == "not_applicable"
    assert not failures(checks)
    assert (rec.account_id, rec.amount_paise, rec.original_reference) == (1, 18_000_000, "N286261234567")
    assert rec.dedup_key == "failure:1:2026-10-12:18000000:N286261234567"


@pytest.mark.parametrize("over, check", [
    ({"amount_text": "one lakh eighty thousand"}, "amount"),
    ({"failure_date": date(2026, 10, 20)}, "dates"),
    ({"uncertain_fields": ["original_reference"]}, "confidence"),
])
def test_a_bad_failure_notice_fails(over, check):
    checks, rec = check_failure_notice(notice(**over), None, MAIL, ACCOUNTS, NO_DUPES)
    assert check in failures(checks) and rec is None


def test_a_repeated_failure_notice_is_a_duplicate():
    checks, rec = check_failure_notice(notice(), None, MAIL, ACCOUNTS, lambda key: 7)
    assert failures(checks) == {"duplicates": "same notice as candidate 7"}


def test_the_dates_window_is_a_kolkata_day():
    # 19:00 UTC on the 12th is 00:30 IST on the 13th: a transaction on the 13th
    # is not "after the email was sent".
    utc_header = MailFacts(BANK, datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc))
    checks, _ = check_bank_alert(alert(txn_date=date(2026, 10, 13)), None, utc_header, ACCOUNTS, NO_DUPES)
    assert checks["dates"] == "passed"
