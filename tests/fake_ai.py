"""A fake ai.client Backend for tests (batch 2 plan, CHG-004). It returns
canned text and token counts and records every request. The canned replies
are written by hand to match each fixture; they show the pipeline handles
what Gemini would send, not that the prompts work on Gemini itself. Only the
PO-authorised `make smoke-gemini` run shows that."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.client import AIUnavailable, Contents, RawAIResponse
from app.ai.fixture_backend import load_replies

INBOX = Path(__file__).resolve().parent.parent / "fixtures" / "test_inbox"


@dataclass
class Request:
    model: str
    system: str
    contents: Contents
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
    # AI the product can do without: with nothing queued, these behave as an AI
    # that is not there (AIUnavailable, permanent) and the code falls back. Any
    # other unqueued call fails the test.
    optional: frozenset[str] = frozenset()

    def queue(self, schema_title: str, *replies: Any) -> FakeBackend:
        self.replies[schema_title].extend(replies)
        return self

    def generate(self, *, model, system, contents, thinking, json_schema) -> RawAIResponse:
        self.requests.append(Request(model, system, contents, thinking, json_schema))
        title = (json_schema or {}).get("title", "")
        if not self.replies[title] and title in self.optional:
            raise AIUnavailable(f"FakeBackend: no {title} queued", retryable=False)
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


# Hand-written replies for the fixtures, as Gemini would send them. One copy, in
# fixtures/ai_replies.json, shared with the demo fixture AI (D15; batch 5, Q6).
FIXTURE_REPLIES: dict[str, list[tuple[str, dict]]] = {
    name: list(replies.items())
    for folder in ("test_inbox", "agent_inbox", "uploads") for name, replies in load_replies(folder).items()
}


def fixture_backend(*names: str) -> FakeBackend:
    """A FakeBackend with the replies for these fixtures queued in order. These
    end-to-end runs replan, so the plan note (optional AI) falls back to the template."""
    backend = FakeBackend(optional=frozenset({"PlanSummary"}))
    for name in names:
        for title, reply in FIXTURE_REPLIES[name]:
            backend.queue(title, reply)
    return backend
