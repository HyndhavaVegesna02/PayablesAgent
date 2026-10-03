"""The checks for a bank statement (TDD Part 1, "Rule checks": statement
arithmetic; batch 5 plan, S5). Pure: the caller passes the accounts and a
lookup for a statement already read."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.money import parse_inr
from app.validate import CHECK_NAMES, NOT_APPLICABLE, PASSED, failed, skipped
from app.validate.alert import AccountIn, MailFacts
from app.validate.arithmetic import check_statement_arithmetic
from app.validate.duplicates import normalise_reference


@dataclass(frozen=True)
class StatementRowRecord:
    txn_date: date
    direction: Literal["debit", "credit"]
    amount_paise: int
    counterparty: str | None
    reference: str | None


@dataclass(frozen=True)
class StatementRecord:
    account_id: int
    period_from: date
    period_to: date
    opening_paise: int
    closing_paise: int
    rows: tuple[StatementRowRecord, ...]
    dedup_key: str


def statement_key(account_id: int, period_from: date, period_to: date) -> str:
    return f"statement:{account_id}:{period_from.isoformat()}:{period_to.isoformat()}"


def _balance(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return parse_inr(text)
    except ValueError:
        return None


def _account(last4: str, mail: MailFacts, accounts: Sequence[AccountIn]) -> tuple[str, AccountIn | None]:
    """By its last four digits; a statement that came by email must also come
    from that account's bank. One the owner uploaded has no sender to check."""
    found = [a for a in accounts if a.last4 == last4]
    if mail.sender is not None:
        found = [a for a in found if mail.sender in a.alert_senders]
    if len(found) != 1:
        return failed(f"no single account of this business ends in {last4}"
                      + (f" with {mail.sender} as its bank" if mail.sender else "")), None
    return PASSED, found[0]


def check_statement(
    extract: BaseModel | None,
    schema_error: str | None,
    mail: MailFacts,
    accounts: Sequence[AccountIn],
    existing_statement: Callable[[str], int | None],
) -> tuple[dict[str, str], StatementRecord | None, None]:
    if extract is None:
        checks = {name: skipped("the reply did not match the schema") for name in CHECK_NAMES}
        checks.update(schema=failed(schema_error or "no reply"), gstin=NOT_APPLICABLE,
                      invoice_arithmetic=NOT_APPLICABLE)
        return checks, None, None
    x = extract
    checks: dict[str, Any] = {name: NOT_APPLICABLE for name in CHECK_NAMES}
    checks["schema"] = PASSED

    problems, rows = [], []
    for i, r in enumerate(x.rows):
        try:
            amount = parse_inr(r.amount_text)
            if amount <= 0:
                raise ValueError
            rows.append(StatementRowRecord(r.txn_date, r.direction, amount, r.counterparty,
                                           normalise_reference(r.reference)))
        except ValueError:
            problems.append(f"row {i + 1} amount {r.amount_text!r} is not an amount in rupees")
    checks["amount"] = failed("; ".join(problems)) if problems else PASSED

    opening, closing = _balance(x.opening_balance_text), _balance(x.closing_balance_text)
    unreadable = [f"{what} {text!r}" for what, text, v in (
        ("opening balance", x.opening_balance_text, opening), ("closing balance", x.closing_balance_text, closing))
        if text is not None and v is None]
    checks["balance"] = failed(f"{', '.join(unreadable)} is not an amount in rupees") if unreadable else PASSED
    if problems or unreadable:
        checks["statement_arithmetic"] = skipped("needs every amount read")
    else:
        checks["statement_arithmetic"] = check_statement_arithmetic(
            opening, [r.amount_paise for r in rows if r.direction == "credit"],
            [r.amount_paise for r in rows if r.direction == "debit"], closing)

    checks["account"], account = _account(x.account_last4, mail, accounts)
    outside = [r.txn_date for r in x.rows if not x.period_from <= r.txn_date <= x.period_to]
    if x.period_to < x.period_from:
        checks["dates"] = failed(f"the period ends {x.period_to}, before it starts {x.period_from}")
    elif outside:
        checks["dates"] = failed(f"rows dated {', '.join(sorted({d.isoformat() for d in outside}))} are outside "
                                 f"the period {x.period_from} to {x.period_to}")
    else:
        checks["dates"] = PASSED

    key = None
    if account is not None:
        key = statement_key(account.id, x.period_from, x.period_to)
        dup = existing_statement(key)
        checks["duplicates"] = PASSED if dup is None else failed(f"the same statement as candidate {dup}")
    else:
        checks["duplicates"] = skipped("needs the account")
    checks["confidence"] = (PASSED if not x.uncertain_fields
                            else failed(f"the model is unsure of {', '.join(sorted(x.uncertain_fields))}"))
    checks = {name: checks[name] for name in CHECK_NAMES}
    if any(v.startswith(("failed", "skipped")) for v in checks.values()):
        return checks, None, None
    return checks, StatementRecord(account.id, x.period_from, x.period_to, opening, closing, tuple(rows), key), None
