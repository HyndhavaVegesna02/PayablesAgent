"""Loading and saving an exception case (batch 6, CHG-008, Q2). The case row is
the agent's working memory, not the ledger: this module's UPDATE of its own
agent_case row is one of the agent's three permitted writes (with candidate
and owner_question; tests/test_agent_boundary.py)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.agent.case_file import parse_opening, render
from app.clock import Clock


@dataclass
class Case:
    id: int
    business_id: int
    kind: str
    subject_ref: str
    stake_paise: int
    thinking: str
    steps: int
    validation_failures: int
    status: str
    escalation_rule: str | None
    state: dict[str, Any] = field(default_factory=dict)
    loaded_status: str = ""  # the status this copy was read with; save() writes only over that

    @property
    def case_file_md(self) -> str:
        return render(self.state)

    def add_note(self, text: str) -> None:
        self.state.setdefault("notes", []).append(text)

    @property
    def seen_message_ids(self) -> set[str]:
        return set(self.state.get("seen_message_ids", []))


class CaseNotFound(LookupError):
    pass


class CaseChanged(Exception):
    """Someone else moved the case while this copy was held: the owner closed
    it, or the reconciler resolved a drift case when the gap closed."""


def load(conn: sqlite3.Connection, case_id: int) -> Case:
    row = conn.execute("SELECT * FROM agent_case WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise CaseNotFound(f"agent_case {case_id} does not exist")
    state = json.loads(row["state_json"] or "{}")
    if not state:  # first run: the reconciler's opening file is the start
        state = parse_opening(row["case_file_md"])
    return Case(row["id"], row["business_id"], row["kind"], row["subject_ref"], row["stake_paise"],
                row["thinking"], row["steps"], row["validation_failures"], row["status"], row["escalation_rule"],
                state, row["status"])


def save(conn: sqlite3.Connection, case: Case, clock: Clock) -> None:
    """Writes the case only if its status is still the one it was read with;
    otherwise raises CaseChanged, and the caller stops."""
    cur = conn.execute(
        "UPDATE agent_case SET thinking = ?, steps = ?, validation_failures = ?, status = ?, escalation_rule = ?, "
        "state_json = ?, case_file_md = ?, updated_at = ? WHERE id = ? AND status = ?",
        (case.thinking, case.steps, case.validation_failures, case.status, case.escalation_rule,
         json.dumps(case.state, sort_keys=True), case.case_file_md, clock.now().isoformat(), case.id,
         case.loaded_status),
    )
    if cur.rowcount == 0:
        (now,) = conn.execute("SELECT status FROM agent_case WHERE id = ?", (case.id,)).fetchone()
        raise CaseChanged(f"agent_case {case.id} is {now} now, not {case.loaded_status}")
    case.loaded_status = case.status
