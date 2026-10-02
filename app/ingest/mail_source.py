"""The mail interface Gmail and the test inbox both implement (TDD Part 2,
"Gmail ingestion"). The rest of the system, including the agent's search
tool, never knows which one it is talking to."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class MessageRef:
    id: str  # Gmail message ID, or the .eml file name in the test inbox


@dataclass(frozen=True)
class Attachment:
    filename: str | None
    content_type: str
    data: bytes


@dataclass(frozen=True)
class RawMessage:
    ref: MessageRef
    raw: bytes  # RFC 2822 bytes, as received
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class MessageSummary:
    ref: MessageRef
    sender: str
    subject: str
    sent_at: datetime | None
    snippet: str


class MailSource(Protocol):
    def list_new(self, since: date, senders: list[str]) -> list[MessageRef]: ...

    def fetch(self, ref: MessageRef) -> RawMessage: ...  # RFC 2822 bytes + attachments

    def search(self, query: str, limit: int = 20) -> list[MessageSummary]: ...
