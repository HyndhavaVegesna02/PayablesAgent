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
