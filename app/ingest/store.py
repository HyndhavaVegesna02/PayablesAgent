"""Stored documents, encrypted with Fernet under DATA_DIR (batch 2 plan, Q8;
TDD Part 2, "Security in code": documents at rest are encrypted). Files are
named by their content hash, so storing the same bytes twice is harmless."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEYGEN_COMMAND = (
    'uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


class StoreKeyError(ValueError):
    """FERNET_KEY is blank or not a Fernet key. The message says how to make
    one; it never includes the key or anything read from .env."""


def _key_help(problem: str) -> str:
    return (
        f"FERNET_KEY {problem}. Documents are stored encrypted, so mail cannot be "
        f"fetched without it. Generate a key with:\n    {KEYGEN_COMMAND}\n"
        "and set FERNET_KEY=<that key> in .env (or the environment), then restart the worker."
    )


class DocumentStore:
    def __init__(self, data_dir: str | Path, fernet_key: str) -> None:
        if not fernet_key.strip():
            raise StoreKeyError(_key_help("is not set"))
        try:
            self._fernet = Fernet(fernet_key.strip().encode())
        except (ValueError, TypeError):
            raise StoreKeyError(_key_help("is not a valid Fernet key")) from None
        self.root = Path(data_dir)

    def put(self, content: bytes, sha256: str) -> str:
        """Encrypts and writes `content`; returns its path relative to DATA_DIR."""
        rel = f"documents/{sha256}.bin"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(self._fernet.encrypt(content))
        tmp.replace(path)
        return rel

    def get(self, rel: str) -> bytes:
        try:
            return self._fernet.decrypt((self.root / rel).read_bytes())
        except InvalidToken:
            raise StoreKeyError(_key_help("does not match the key these documents were stored with")) from None
