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

from app.ai.email_text import body_text
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
        among messages already released; newest first. Gmail's own operators
        work as they do there (CHG-031: the live agent used `from:`):
        `from:` and `subject:` match within that header, `after:` keeps
        messages on or after a day and `before:` those before it
        (YYYY/MM/DD or YYYY-MM-DD)."""
        words, where, after, before = [], [], None, None
        for w in query.lower().split():
            op, _, value = w.partition(":")
            if op in ("after", "before") and value:
                try:
                    day = date.fromisoformat(value.replace("/", "-"))
                except ValueError:
                    words.append(w)
                    continue
                after, before = (day, before) if op == "after" else (after, day)
            elif op in ("from", "subject") and value:
                where.append((op, value))
            else:
                words.append(w)
        found = []
        for f in self._files():
            msg = parse_message(f.read_bytes())
            if not self._released(msg):
                continue
            at = sent_at(msg)
            day = at.astimezone(TIMEZONE).date() if at else None
            if (after or before) and (day is None or (after and day < after) or (before and day >= before)):
                continue
            headers = {"from": str(msg.get("From", "")).lower(), "subject": str(msg.get("Subject", "")).lower()}
            if not all(value in headers[op] for op, value in where):
                continue
            body = body_text(msg)
            haystack = " ".join([headers["from"], headers["subject"], body.lower()])
            if all(w in haystack for w in words):
                found.append(MessageSummary(
                    MessageRef(f.name), sender_address(msg) or "", str(msg.get("Subject", "")),
                    sent_at(msg), " ".join(body.split())[:160],
                ))
        found.sort(key=lambda s: (s.sent_at is not None, s.sent_at.timestamp() if s.sent_at else 0), reverse=True)
        return found[:limit]
