"""EmlFolderSource: the test inbox (TDD Part 2, "Gmail ingestion"). Reads
.eml files from a folder and releases each one when the injected Clock
reaches its Date header, so a scenario can play emails out day by day.

A file with a missing or unreadable Date header is listed straight away, so
the pipeline records it as FAILED instead of it silently never arriving."""

from __future__ import annotations

import email
import email.policy
import email.utils
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from app.clock import TIMEZONE, Clock
from app.ingest.mail_source import Attachment, MessageRef, MessageSummary, RawMessage


def parse_message(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[return-value]


def sent_at(msg: EmailMessage) -> datetime | None:
    """The Date header as an aware datetime, or None if missing or unreadable."""
    value = msg.get("Date")
    if value is None:
        return None
    try:
        d = email.utils.parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo is not None else None  # a Date with no zone is unreadable for us


def sender_address(msg: EmailMessage) -> str | None:
    value = msg.get("From")
    if value is None:
        return None
    _, addr = email.utils.parseaddr(str(value))
    return addr.lower() or None


def body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    return part.get_content()


def attachments(msg: EmailMessage) -> tuple[Attachment, ...]:
    return tuple(
        Attachment(a.get_filename(), a.get_content_type(), a.get_payload(decode=True) or b"")
        for a in msg.iter_attachments()
    )


class EmlFolderSource:
    def __init__(self, path: str | Path, clock: Clock) -> None:
        self.path = Path(path)
        self.clock = clock

    def _files(self) -> list[Path]:
        return sorted(self.path.glob("*.eml"))

    def _released(self, msg: EmailMessage) -> bool:
        at = sent_at(msg)
        return at is None or at <= self.clock.now()

    def list_new(self, since: date, senders: list[str]) -> list[MessageRef]:
        wanted = {s.lower() for s in senders}
        refs = []
        for f in self._files():
            msg = parse_message(f.read_bytes())
            if sender_address(msg) not in wanted or not self._released(msg):
                continue
            at = sent_at(msg)
            if at is not None and at.astimezone(TIMEZONE).date() < since:
                continue
            refs.append(MessageRef(f.name))
        return refs

    def fetch(self, ref: MessageRef) -> RawMessage:
        path = self.path / ref.id
        if path.parent != self.path or path.suffix != ".eml":
            raise ValueError(f"not a test-inbox message: {ref.id!r}")
        raw = path.read_bytes()
        return RawMessage(ref, raw, attachments(parse_message(raw)))

    def search(self, query: str, limit: int = 20) -> list[MessageSummary]:
        """Case-insensitive match of every word over sender, subject and body,
        among messages already released; newest first."""
        words = query.lower().split()
        found = []
        for f in self._files():
            msg = parse_message(f.read_bytes())
            if not self._released(msg):
                continue
            body = body_text(msg)
            haystack = " ".join([str(msg.get("From", "")), str(msg.get("Subject", "")), body]).lower()
            if all(w in haystack for w in words):
                found.append(MessageSummary(
                    MessageRef(f.name), sender_address(msg) or "", str(msg.get("Subject", "")),
                    sent_at(msg), " ".join(body.split())[:160],
                ))
        found.sort(key=lambda s: (s.sent_at is not None, s.sent_at and s.sent_at.isoformat()), reverse=True)
        return found[:limit]
