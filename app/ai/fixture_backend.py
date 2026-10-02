"""The demo's fixture AI (batch 3 plan, PO decision D15). With DEMO_AI=fixtures
the worker answers from the canned replies beside the test inbox
(ai_replies.json, the same copy the tests use) instead of calling Gemini.

It is honest about what it is: the worker records it as model "fixture-ai"
with no tokens and no cost, and the web app shows a demo banner. An email
with no canned reply is AIUnavailable (permanent): never a guess, and never
a fall-back to Gemini."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ai.client import AIUnavailable, RawAIResponse
from app.ai.email_text import email_text_from_bytes

FIXTURE_MODEL = "fixture-ai"
REPLIES_FILE = "ai_replies.json"
# The one copy of the fixtures and their replies. A demo delivers mail by copying
# files from here into its own TEST_INBOX_PATH, as the tests do.
FIXTURE_INBOX = Path(__file__).resolve().parents[2] / "fixtures" / "test_inbox"


def load_replies(inbox: str | Path) -> dict[str, dict[str, Any]]:
    """File name -> {schema title: reply}. A string entry names the file
    whose replies it shares (a re-sent alert)."""
    raw = json.loads((Path(inbox) / REPLIES_FILE).read_text(encoding="utf-8"))["replies"]
    return {name: raw[entry] if isinstance(entry, str) else entry for name, entry in raw.items()}


class FixtureBackend:
    def __init__(self, inbox: str | Path = FIXTURE_INBOX) -> None:
        self.replies = load_replies(inbox)
        # What the model is shown of each fixture email; a request is matched to
        # the fixture whose text it contains.
        self.texts = {
            f.name: email_text_from_bytes(f.read_bytes())
            for f in sorted(Path(inbox).glob("*.eml")) if f.name in self.replies
        }

    def generate(self, *, model: str, system: str, contents: str, thinking: str,
                 json_schema: dict[str, Any] | None) -> RawAIResponse:
        title = (json_schema or {}).get("title", "")
        for name, text in self.texts.items():
            if text in contents and title in self.replies[name]:
                return RawAIResponse(json.dumps(self.replies[name][title]), 0, 0, 0)
        raise AIUnavailable(f"the demo fixture AI has no canned {title or 'reply'} for this email",
                            retryable=False)
