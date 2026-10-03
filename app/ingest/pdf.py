"""Password-protected PDFs (TDD Part 1: "PyMuPDF unlocks the PDF using a
password the owner types when the statement arrives. The password is used
once and never stored"; batch 5 plan, S5).

The password is an argument and nothing else: it is never logged, traced,
stored, put in an exception message or returned. What is kept is the
unlocked document, encrypted at rest like every stored file."""

from __future__ import annotations

import email
import email.policy
from email.message import EmailMessage

import pymupdf

PDF = "application/pdf"


def is_locked(data: bytes) -> bool:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return bool(doc.needs_pass)
    except Exception:  # not a PDF PyMuPDF can open: the model or the checks will say so
        return False


def unlock(data: bytes, password: str) -> bytes | None:
    """The PDF without its password, or None when the password does not open it."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if not doc.needs_pass:
                return data
            if not doc.authenticate(password):
                return None
            return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE)
    except Exception:
        return None


def locked_attachments(msg: EmailMessage) -> list[EmailMessage]:
    return [a for a in msg.iter_attachments()
            if a.get_content_type() == PDF and is_locked(a.get_payload(decode=True) or b"")]


def unlock_email(raw: bytes, password: str) -> bytes | None:
    """The email with each locked PDF attachment replaced by its unlocked copy,
    or None when the password does not open one of them."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    for part in locked_attachments(msg):  # type: ignore[arg-type]
        opened = unlock(part.get_payload(decode=True) or b"", password)
        if opened is None:
            return None
        part.set_content(opened, maintype="application", subtype="pdf", filename=part.get_filename())
    return msg.as_bytes(policy=email.policy.default)
