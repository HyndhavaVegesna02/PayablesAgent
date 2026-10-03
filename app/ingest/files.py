"""What kind of file an upload or attachment is, from its first bytes (the
browser's content type is not kept, and is only a claim). Gemini needs the
mime type with each file it is sent (batch 5 plan, S2 and S3)."""

from __future__ import annotations

# The files the model reads: photos, PDFs and voice notes.
READABLE = ("application/pdf", "image/", "audio/")


def sniff_mime(data: bytes, kind: str) -> str | None:
    """The mime type of a stored photo, PDF or voice note, or None when the
    bytes are not one the model can read."""
    head = data[:16]
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if head[4:8] == b"ftyp":
        return "audio/mp4" if kind == "voice" else "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm" if kind == "voice" else "video/webm"
    return None


def readable(content_type: str) -> bool:
    return any(content_type == t or (t.endswith("/") and content_type.startswith(t)) for t in READABLE)
