"""Sending one owner alert email (TDD Part 2, "Security in code": a fixed
recipient from the database, and an SMTP account separate from Gmail). STARTTLS
on the configured port (587 by default). Any smtplib or socket error is raised
for the job queue to retry."""

from __future__ import annotations

import re
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage

DEFAULT_PORT = 587
_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


def message(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    for value in (sender, recipient):
        if not _ADDRESS.fullmatch(value):
            raise ValueError(f"not a plain email address: {value!r}")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, recipient, subject
    msg.set_content(body)  # text/plain only
    return msg


def send_email(msg: EmailMessage, *, host: str, port: int | None, user: str, password: str,
               smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP) -> None:
    with smtp_factory(host, port or DEFAULT_PORT, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        if user:
            server.login(user, password)
        server.send_message(msg)
