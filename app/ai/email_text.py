"""What Gemini sees of an email: the From, Date and Subject headers, then the
text body. Other headers (Message-ID, X-* notes) are left out."""

from __future__ import annotations

import email
import email.policy
from email.message import EmailMessage


def email_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part is not None else ""
    return (
        f"From: {msg.get('From', '')}\nDate: {msg.get('Date', '')}\nSubject: {msg.get('Subject', '')}\n\n"
        f"{body.strip()}\n"
    )


def email_text_from_bytes(raw: bytes) -> str:
    return email_text(email.message_from_bytes(raw, policy=email.policy.default))  # type: ignore[arg-type]
