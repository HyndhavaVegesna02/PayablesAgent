"""Every Part 1 rule check for a bank alert or a failure/return notice (batch 2
plan, CHG-004 AC4 and Q3). The checks turn the model's text into the values
the ledger stores: amounts through parse_inr, the account through the
business's own accounts, the dedup key built here. Nothing the model wrote
is stored as a number."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.money import parse_inr
from app.validate import CHECK_NAMES, NOT_APPLICABLE, NOT_FOR_MAIL_ALERTS, PASSED, failed, skipped
from app.validate.dates import check_mail_date
from app.validate.duplicates import failure_dedup_key, normalise_reference, txn_dedup_key


@dataclass(frozen=True)
class AccountIn:
    id: int
    last4: str
    alert_senders: frozenset[str]  # lower-case addresses


@dataclass(frozen=True)
class MailFacts:
    sender: str | None  # lower-case address from the From header
    sent_at: datetime | None


@dataclass(frozen=True)
class AlertRecord:
    account_id: int
    direction: Literal["debit", "credit"]
    amount_paise: int
    txn_date: date
    counterparty: str | None
    reference: str | None
    balance_after_paise: int | None
    dedup_key: str


@dataclass(frozen=True)
class FailureRecord:
    account_id: int
    amount_paise: int
    failure_date: date
    original_reference: str | None
    reason: str
    dedup_key: str


def _amount(text: str, what: str) -> tuple[str, int | None]:
    try:
        paise = parse_inr(text)
    except ValueError:
        return failed(f"{what} {text!r} is not an amount in rupees"), None
    if paise <= 0:
        return failed(f"{what} {text!r} is not more than zero"), None
    return PASSED, paise


def _account(last4: str, mail: MailFacts, accounts: Sequence[AccountIn]) -> tuple[str, AccountIn | None]:
    by_digits = [a for a in accounts if a.last4 == last4]
    if not by_digits:
        return failed(f"no account of this business ends in {last4}"), None
    sent_by = [a for a in by_digits if mail.sender in a.alert_senders]
    if len(sent_by) != 1:
        return failed(f"{mail.sender or 'no sender'} is not an alert sender for the account ending {last4}"), None
    return PASSED, sent_by[0]


def _confidence(uncertain: list[str]) -> str:
    return PASSED if not uncertain else failed(f"the model is unsure of {', '.join(sorted(uncertain))}")


def _all(checks: dict[str, str]) -> dict[str, str]:
    """Every Part 1 check, in order; the ones that do not apply to mail say so."""
    for name in NOT_FOR_MAIL_ALERTS:
        checks.setdefault(name, NOT_APPLICABLE)
    return {name: checks[name] for name in CHECK_NAMES}


def _schema_failed(schema_error: str | None) -> dict[str, str]:
    checks = {"schema": failed(schema_error or "no reply")}
    for name in CHECK_NAMES:
        if name not in NOT_FOR_MAIL_ALERTS and name != "schema":
            checks[name] = skipped("the reply did not match the schema")
    return _all(checks)


def check_bank_alert(
    extract: BaseModel | None,
    schema_error: str | None,
    mail: MailFacts,
    accounts: Sequence[AccountIn],
    existing_txn: Callable[[str], int | None],
) -> tuple[dict[str, str], AlertRecord | None]:
    if extract is None:
        return _schema_failed(schema_error), None
    x = extract
    checks = {"schema": PASSED}
    checks["amount"], amount = _amount(x.amount_text, "amount")
    balance = None
    if x.available_balance_text is None:
        checks["balance"] = NOT_APPLICABLE
    else:
        try:
            balance = parse_inr(x.available_balance_text)
            checks["balance"] = PASSED
        except ValueError:
            checks["balance"] = failed(f"available balance {x.available_balance_text!r} is not an amount in rupees")
    checks["account"], account = _account(x.account_last4, mail, accounts)
    checks["dates"] = check_mail_date(x.txn_date, mail.sent_at)
    key = None
    if account is not None and amount is not None:
        key = txn_dedup_key(account.id, x.txn_date, x.direction, amount, x.reference)
        dup = existing_txn(key)
        checks["duplicates"] = PASSED if dup is None else failed(f"same as bank transaction {dup}")
    else:
        checks["duplicates"] = skipped("needs a valid account and amount")
    checks["confidence"] = _confidence(x.uncertain_fields)
    checks = _all(checks)
    if any(v.startswith(("failed", "skipped")) for v in checks.values()):
        return checks, None
    return checks, AlertRecord(
        account.id, x.direction, amount, x.txn_date, x.counterparty, normalise_reference(x.reference),
        balance, key,
    )


def check_failure_notice(
    extract: BaseModel | None,
    schema_error: str | None,
    mail: MailFacts,
    accounts: Sequence[AccountIn],
    existing_notice: Callable[[str], int | None],
) -> tuple[dict[str, str], FailureRecord | None]:
    if extract is None:
        return _schema_failed(schema_error), None
    x = extract
    checks = {"schema": PASSED, "balance": NOT_APPLICABLE}
    checks["amount"], amount = _amount(x.amount_text, "amount")
    checks["account"], account = _account(x.account_last4, mail, accounts)
    checks["dates"] = check_mail_date(x.failure_date, mail.sent_at, what="failure")
    key = None
    if account is not None and amount is not None:
        key = failure_dedup_key(account.id, x.failure_date, amount, x.original_reference)
        dup = existing_notice(key)
        checks["duplicates"] = PASSED if dup is None else failed(f"same notice as candidate {dup}")
    else:
        checks["duplicates"] = skipped("needs a valid account and amount")
    checks["confidence"] = _confidence(x.uncertain_fields)
    checks = _all(checks)
    if any(v.startswith(("failed", "skipped")) for v in checks.values()):
        return checks, None
    return checks, FailureRecord(
        account.id, amount, x.failure_date, normalise_reference(x.original_reference), x.reason, key,
    )
