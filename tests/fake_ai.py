"""A fake ai.client Backend for tests (batch 2 plan, CHG-004). It returns
canned text and token counts and records every request. The canned replies
are written by hand to match each fixture; they show the pipeline handles
what Gemini would send, not that the prompts work on Gemini itself. Only the
PO-authorised `make smoke-gemini` run shows that."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from app.ai.client import AIUnavailable, RawAIResponse


@dataclass
class Request:
    model: str
    system: str
    contents: str
    thinking: str
    json_schema: dict[str, Any] | None


@dataclass
class FakeBackend:
    """Replies are queued per schema title ("SortResult", "BankAlertExtract",
    ...) and served in order. A reply is a dict (sent as JSON), a str (sent
    as is), None (no text, like a blocked response) or an exception."""

    replies: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    requests: list[Request] = field(default_factory=list)
    usage: tuple[int, int, int] = (1000, 100, 50)

    def queue(self, schema_title: str, *replies: Any) -> FakeBackend:
        self.replies[schema_title].extend(replies)
        return self

    def generate(self, *, model, system, contents, thinking, json_schema) -> RawAIResponse:
        self.requests.append(Request(model, system, contents, thinking, json_schema))
        title = (json_schema or {}).get("title", "")
        if not self.replies[title]:
            raise AssertionError(f"FakeBackend has no reply queued for {title!r}")
        reply = self.replies[title].popleft()
        if isinstance(reply, Exception):
            raise reply
        text = json.dumps(reply) if isinstance(reply, dict) else reply
        return RawAIResponse(text, *self.usage)

    def calls(self, schema_title: str) -> list[Request]:
        return [r for r in self.requests if (r.json_schema or {}).get("title") == schema_title]


def unavailable(retryable: bool = True) -> AIUnavailable:
    return AIUnavailable("fake outage", retryable=retryable, code=503 if retryable else 400)


# Hand-written replies for fixtures/test_inbox, as Gemini would send them.
_ALERT_SORT = {"doc_type": "bank_alert", "reason": "A bank alert for a debit or credit."}
FIXTURE_REPLIES: dict[str, list[tuple[str, dict]]] = {
    "01-debit-ashirwad-paper.eml": [
        ("SortResult", _ALERT_SORT),
        ("BankAlertExtract", {
            "account_last4": "4821", "direction": "debit", "amount_text": "Rs.1,80,000.00",
            "txn_date": "2026-10-12", "counterparty": "ASHIRWAD PAPER SUPPLIERS",
            "reference": "N286261234567", "available_balance_text": "Rs.4,40,000.00",
            "uncertain_fields": [],
        }),
    ],
    "02-credit-kaveri-traders.eml": [
        ("SortResult", _ALERT_SORT),
        ("BankAlertExtract", {
            "account_last4": "4821", "direction": "credit", "amount_text": "Rs.33,000.00",
            "txn_date": "2026-10-13", "counterparty": "KAVERI TRADERS", "reference": "N287265551210",
            "available_balance_text": "Rs.4,73,000.00", "uncertain_fields": [],
        }),
    ],
    "03-return-ashirwad-paper.eml": [
        ("SortResult", {"doc_type": "failure_notice", "reason": "An NEFT payment was returned."}),
        ("FailureNoticeExtract", {
            "account_last4": "4821", "amount_text": "Rs.1,80,000.00",
            "original_reference": "N286261234567", "failure_date": "2026-10-14",
            "reason": "Beneficiary account closed or transferred", "uncertain_fields": [],
        }),
    ],
    "04-debit-city-electricity-balance-short.eml": [
        ("SortResult", _ALERT_SORT),
        ("BankAlertExtract", {
            "account_last4": "4821", "direction": "debit", "amount_text": "Rs.35,000.00",
            "txn_date": "2026-10-15", "counterparty": "CITY ELECTRICITY BOARD",
            "reference": "BP2610150098812", "available_balance_text": "Rs.5,65,000.00",
            "uncertain_fields": [],
        }),
    ],
    "05-offer-newsletter.eml": [
        ("SortResult", {"doc_type": "irrelevant", "reason": "A promotional email."}),
    ],
}
FIXTURE_REPLIES["06-debit-ashirwad-paper-resent.eml"] = FIXTURE_REPLIES["01-debit-ashirwad-paper.eml"]


def fixture_backend(*names: str) -> FakeBackend:
    """A FakeBackend with the replies for these fixtures queued in order."""
    backend = FakeBackend()
    for name in names:
        for title, reply in FIXTURE_REPLIES[name]:
            backend.queue(title, reply)
    return backend
