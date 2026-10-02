"""Allowed state moves and actor parsing (TDD Part 2, "Ledger writer").

The payable table is Part 2's, verbatim. The bank_txn and receivable tables
hold only rows the TDD states (batch 1 plan, D2); every other move is refused
until a later change cites it. Any agent actor is refused before any table
is consulted, so no table edit can let the AI move money state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, get_args

from app.domain.models import PayableStatus

Role = Literal["owner", "planner", "reconciler", "pipeline"]
EntityKind = Literal["payable", "receivable", "bank_txn"]


class TransitionRefused(Exception):
    """Base for every refusal by the ledger writer."""


class AgentActorRefused(TransitionRefused):
    pass


class InvalidActor(TransitionRefused):
    pass


class ActorNotAllowed(TransitionRefused):
    pass


class IllegalTransition(TransitionRefused):
    pass


class VersionRequired(TransitionRefused):
    pass


class StaleVersion(TransitionRefused):
    pass


class FieldNotAllowed(TransitionRefused):
    pass


class RecordNotFound(TransitionRefused):
    pass


@dataclass(frozen=True)
class Actor:
    role: Role
    owner_id: int | None


_OWNER = re.compile(r"owner:([1-9][0-9]*)")
_SYSTEM_ROLES: frozenset[str] = frozenset({"planner", "reconciler", "pipeline"})


def parse_actor(actor: str) -> Actor:
    if not isinstance(actor, str):
        raise InvalidActor(f"actor must be a string, got {type(actor).__name__}")
    if actor.lower().startswith("agent"):
        raise AgentActorRefused(f"agent actors may not change ledger state: {actor!r}")
    if actor in _SYSTEM_ROLES:
        return Actor(actor, None)  # type: ignore[arg-type]
    m = _OWNER.fullmatch(actor)
    if m:
        return Actor("owner", int(m.group(1)))
    raise InvalidActor(f"unrecognised actor {actor!r}")


PAYABLE_STATES: tuple[str, ...] = get_args(PayableStatus)

PAYABLE_TRANSITIONS: dict[tuple[str, str], frozenset[Role]] = {
    ("DRAFT", "CONFIRMED"): frozenset({"owner"}),
    ("CONFIRMED", "PLANNED"): frozenset({"planner"}),
    ("PLANNED", "CONFIRMED"): frozenset({"planner"}),
    ("REOPENED", "PLANNED"): frozenset({"planner"}),
    ("PLANNED", "PAYMENT_EXPECTED"): frozenset({"owner"}),
    ("PAYMENT_EXPECTED", "PAID"): frozenset({"reconciler", "owner"}),
    ("PAYMENT_EXPECTED", "REVIEW"): frozenset({"reconciler"}),
    ("PAYMENT_EXPECTED", "REOPENED"): frozenset({"reconciler"}),
    ("REVIEW", "PAID"): frozenset({"owner"}),
    ("REVIEW", "REOPENED"): frozenset({"owner"}),
    ("PAID", "REOPENED"): frozenset({"reconciler"}),
    # Reached only through ledger.writer.split_payable, which also creates the children.
    ("CONFIRMED", "SPLIT"): frozenset({"owner"}),
    ("PLANNED", "SPLIT"): frozenset({"owner"}),
}

BANK_TXN_TRANSITIONS: dict[tuple[str, str], frozenset[Role]] = {
    ("UNMATCHED", "MATCHED"): frozenset({"reconciler"}),
    ("MATCHED", "REVERSED"): frozenset({"reconciler"}),
    # A failure or return email whose debit was never matched (batch 2 plan, Q7;
    # TDD "Failures and reversals": "any original debit is marked REVERSED").
    ("UNMATCHED", "REVERSED"): frozenset({"reconciler"}),
}

# bank_account.drift_status (TDD Part 2, "Drift check"; batch 2 plan, CHG-005).
# Changed only through ledger.writer (set_drift_status, confirm_balance).
DRIFT_TRANSITIONS: dict[tuple[str, str], frozenset[Role]] = {
    ("OK", "CHECKING"): frozenset({"reconciler"}),  # step 4: a mismatch remains
    ("CHECKING", "OK"): frozenset({"reconciler"}),  # step 5: findings close the gap
    ("CHECKING", "ASK_OWNER"): frozenset({"reconciler"}),  # step 5: they do not
    ("ASK_OWNER", "OK"): frozenset({"owner"}),  # step 6: confirm_balance only
}

RECEIVABLE_TRANSITIONS: dict[tuple[str, str], frozenset[Role]] = {
    ("COMMITTED", "CONFIRMED"): frozenset({"reconciler"}),
    ("EXPECTED", "CONFIRMED"): frozenset({"reconciler"}),
    ("UNKNOWN", "CONFIRMED"): frozenset({"reconciler"}),
}

TRANSITIONS: dict[EntityKind, dict[tuple[str, str], frozenset[Role]]] = {
    "payable": PAYABLE_TRANSITIONS,
    "receivable": RECEIVABLE_TRANSITIONS,
    "bank_txn": BANK_TXN_TRANSITIONS,
}

STATE_COLUMN: dict[EntityKind, str] = {
    "payable": "status",
    "receivable": "confidence",
    "bank_txn": "status",
}

# Initial state -> roles allowed to create a record in it.
CREATE_RULES: dict[EntityKind, dict[str, frozenset[Role]]] = {
    "payable": {"DRAFT": frozenset({"pipeline", "owner"})},
    "receivable": {
        "COMMITTED": frozenset({"owner"}),
        "EXPECTED": frozenset({"owner"}),
        "UNKNOWN": frozenset({"owner"}),
    },
    "bank_txn": {
        # The owner too, when confirming an alert the rule checks could not settle
        # (TDD pipeline step 5: "ask the owner to fill the fields that still fail").
        "UNMATCHED": frozenset({"pipeline", "owner"}),
        "ADJUSTMENT": frozenset({"owner"}),
    },
}


@dataclass(frozen=True)
class FieldRule:
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()


# Caller-supplied columns a move may set besides the state column. Anything
# else passed to transition() is refused. Columns the writer derives itself
# (approved_by/approved_at, clearing planned_date) are not listed here.
TRANSITION_FIELDS: dict[tuple[EntityKind, str], FieldRule] = {
    ("payable", "PLANNED"): FieldRule(required=frozenset({"planned_date"})),
    ("payable", "PAID"): FieldRule(optional=frozenset({"matched_txn_id"})),
    ("receivable", "CONFIRMED"): FieldRule(optional=frozenset({"matched_txn_id"})),
    ("bank_txn", "MATCHED"): FieldRule(optional=frozenset({"party_id"})),
}
