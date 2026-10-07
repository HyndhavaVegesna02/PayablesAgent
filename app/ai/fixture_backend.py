"""The demo's fixture AI (batch 3 plan, PO decision D15). With DEMO_AI=fixtures
the worker answers from the canned replies in fixtures/ai_replies.json (the
same copy the tests use) instead of calling Gemini.

It is honest about what it is: the worker records it as model "fixture-ai"
with no tokens and no cost, and the web app shows a demo banner. A document
with no canned reply is AIUnavailable (permanent): never a guess, and never
a fall-back to Gemini.

An email is matched by its text (a demo delivers mail by copying files from
fixtures/test_inbox into its own TEST_INBOX_PATH, as the tests do); an
uploaded photo, PDF or voice note by the sha256 of its bytes against the
files in fixtures/uploads (batch 5 plan, S2 and Q6).

Another demo profile brings its own store (FIXTURE_REPLIES_PATH, CHG-058). Its
`_email_folders` and `_upload_folders` name the folders under fixtures/ that its
replies are for; this store's are test_inbox and agent_inbox, and uploads."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.ai.client import AIUnavailable, Contents, RawAIResponse
from app.ai.email_text import email_text_from_bytes

FIXTURE_MODEL = "fixture-ai"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
REPLIES_FILE = FIXTURES / "ai_replies.json"
FIXTURE_INBOX = FIXTURES / "test_inbox"
FIXTURE_AGENT_INBOX = FIXTURES / "agent_inbox"  # mail only the agent tests and evals deliver (not the demo's inbox)
FIXTURE_UPLOADS = FIXTURES / "uploads"


def _store(path: Path | None) -> dict[str, Any]:
    return json.loads((path or REPLIES_FILE).read_text(encoding="utf-8"))


def load_replies(folder: str, store: Path | None = None) -> dict[str, dict[str, Any]]:
    """File name -> {schema title: reply} for one fixture folder ("test_inbox"
    or "uploads"). A string entry names the file whose replies it shares (a
    re-sent alert)."""
    raw = _store(store).get(folder, {})
    return {name: raw[entry] if isinstance(entry, str) else entry for name, entry in raw.items()}


NO_SCRIPT = {"notes": "the demo assistant has no script for this case", "final": {
    "outcome": "NEEDS_OWNER", "summary": "The demo assistant has no script for this case. Please look at it.",
    "cited_message_ids": [], "relied_on_candidate_ids": []}}


def load_agent_scripts(store: Path | None = None) -> list[dict[str, Any]]:
    """The exception agent's scripted steps, from the replies store."""
    return _store(store).get("agent_scripts", [])


def agent_step(scripts: list[dict[str, Any]], case_file: str) -> dict[str, Any]:
    """The scripted AgentStep for this case file (see the store's
    _agent_scripts_note). It reads only the case file, as Gemini would: the
    step number from its notes, VALID candidates from its findings."""
    for script in scripts:
        if script["case"] not in case_file:
            continue
        for rule in script["rules"]:
            if all(t in case_file for t in rule.get("if", [])) and not any(
                    t in case_file for t in rule.get("unless", [])):
                step = 1 + max((int(n) for n in re.findall(r"^- step (\d+): ", case_file, re.M)), default=0)
                valid = sorted({int(c) for c in re.findall(r"candidate (\d+): VALID", case_file)})
                text = json.dumps(rule["step"], ensure_ascii=False).replace("{step}", str(step))
                return json.loads(text.replace('"$valid_candidates"', json.dumps(valid)))
        break
    return NO_SCRIPT


def _folders(raw: dict[str, Any], key: str, default: list[Path]) -> list[Path]:
    """The fixture folders a store's replies are for: its own list under fixtures/, or this store's."""
    return [FIXTURES / name for name in raw[key]] if key in raw else default


NO_CANNED_REPLY = "the demo fixture AI has no canned"  # a gap in the script, not a model that was down

class FixtureBackend:
    def __init__(self, store: Path | None = None) -> None:
        raw = _store(store)
        email_folders = _folders(raw, "_email_folders", [FIXTURE_INBOX, FIXTURE_AGENT_INBOX])
        upload_folders = _folders(raw, "_upload_folders", [FIXTURE_UPLOADS])
        emails = {n: r for f in email_folders for n, r in load_replies(f.name, store).items()}
        uploads = {n: r for f in upload_folders for n, r in load_replies(f.name, store).items()}
        # What the model is shown of each fixture email; a request is matched to
        # the fixture whose text it contains.
        self.texts = {
            f.name: email_text_from_bytes(f.read_bytes())
            for f in sorted(f for folder in email_folders for f in folder.glob("*.eml")) if f.name in emails
        }
        self.email_replies = emails
        self.scripts = load_agent_scripts(store)
        self.file_replies = {
            hashlib.sha256(f.read_bytes()).hexdigest(): uploads[f.name]
            for folder in upload_folders for f in sorted(folder.glob("*")) if f.name in uploads
        }

    def _replies_for(self, contents: Contents) -> list[dict[str, Any]]:
        items = [contents] if isinstance(contents, str) else list(contents)
        found = []
        for item in items:
            if isinstance(item, str):
                found += [self.email_replies[n] for n, text in self.texts.items() if text and text in item]
            elif item.sha256 in self.file_replies:
                found.append(self.file_replies[item.sha256])
        return found

    def generate(self, *, model: str, system: str, contents: Contents, thinking: str,
                 json_schema: dict[str, Any] | None) -> RawAIResponse:
        title = (json_schema or {}).get("title", "")
        if title == "AgentStep" and isinstance(contents, str):
            return RawAIResponse(json.dumps(agent_step(self.scripts, contents)), 0, 0, 0)
        for replies in self._replies_for(contents):
            if title in replies:
                return RawAIResponse(json.dumps(replies[title]), 0, 0, 0)
        raise AIUnavailable(f"{NO_CANNED_REPLY} {title or 'reply'} for this document", retryable=False)
