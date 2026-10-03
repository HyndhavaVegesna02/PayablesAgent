import pytest

from app.domain.states import (
    BANK_TXN_TRANSITIONS,
    DRIFT_TRANSITIONS,
    CREATE_RULES,
    PAYABLE_TRANSITIONS,
    RECEIVABLE_TRANSITIONS,
    Actor,
    AgentActorRefused,
    InvalidActor,
    parse_actor,
)

# TDD Part 2, "Ledger writer" — transcribed row by row.
PART2_TABLE = {
    ("DRAFT", "CONFIRMED"): {"owner"},
    ("CONFIRMED", "PLANNED"): {"planner"},
    ("PLANNED", "CONFIRMED"): {"planner"},
    ("REOPENED", "PLANNED"): {"planner"},
    ("PLANNED", "PAYMENT_EXPECTED"): {"owner"},
    ("PAYMENT_EXPECTED", "PAID"): {"reconciler", "owner"},
    ("PAYMENT_EXPECTED", "REVIEW"): {"reconciler"},
    ("PAYMENT_EXPECTED", "REOPENED"): {"reconciler"},
    ("REVIEW", "PAID"): {"owner"},
    ("REVIEW", "REOPENED"): {"owner"},
    ("REVIEW", "PAYMENT_EXPECTED"): {"owner"},
    ("PAID", "REOPENED"): {"reconciler"},
    ("CONFIRMED", "SPLIT"): {"owner"},
    ("PLANNED", "SPLIT"): {"owner"},
}


def test_payable_table_is_exactly_part2():
    assert {k: set(v) for k, v in PAYABLE_TRANSITIONS.items()} == PART2_TABLE


def test_bank_txn_table_has_only_the_cited_rows():
    assert {k: set(v) for k, v in BANK_TXN_TRANSITIONS.items()} == {
        ("UNMATCHED", "MATCHED"): {"reconciler", "owner"},
        ("MATCHED", "REVERSED"): {"reconciler"},
        ("UNMATCHED", "REVERSED"): {"reconciler"},  # batch 2, Q7
    }


def test_drift_table_is_the_tdd_drift_check():
    assert {k: set(v) for k, v in DRIFT_TRANSITIONS.items()} == {
        ("OK", "CHECKING"): {"reconciler"},
        ("CHECKING", "OK"): {"reconciler"},
        ("CHECKING", "ASK_OWNER"): {"reconciler"},
        ("ASK_OWNER", "OK"): {"owner"},
    }


def test_receivable_table_has_only_the_cited_rows():
    assert {k: set(v) for k, v in RECEIVABLE_TRANSITIONS.items()} == {
        ("COMMITTED", "CONFIRMED"): {"reconciler"},
        ("EXPECTED", "CONFIRMED"): {"reconciler"},
        ("UNKNOWN", "CONFIRMED"): {"reconciler"},
    }


def test_create_rules():
    assert {k: {s: set(r) for s, r in v.items()} for k, v in CREATE_RULES.items()} == {
        "payable": {"DRAFT": {"pipeline", "owner"}},
        "receivable": {
            "COMMITTED": {"owner"}, "EXPECTED": {"owner"}, "UNKNOWN": {"owner"},
        },
        "bank_txn": {"UNMATCHED": {"pipeline", "owner"}, "ADJUSTMENT": {"owner"}},
    }


@pytest.mark.parametrize(
    "text, expected",
    [
        ("owner:1", Actor("owner", 1)),
        ("owner:42", Actor("owner", 42)),
        ("planner", Actor("planner", None)),
        ("reconciler", Actor("reconciler", None)),
        ("pipeline", Actor("pipeline", None)),
    ],
)
def test_parse_actor_accepts_the_four_forms(text, expected):
    assert parse_actor(text) == expected


@pytest.mark.parametrize("text", ["agent:case:1", "agent:", "agent", "AGENT:case:1"])
def test_parse_actor_refuses_agents(text):
    with pytest.raises(AgentActorRefused):
        parse_actor(text)


def test_parse_actor_refuses_non_strings():
    with pytest.raises(InvalidActor):
        parse_actor(None)


@pytest.mark.parametrize(
    "text", ["Owner:1", "owner:", "owner:abc", "owner:0", "owner:01", "planner:1", "", "seed", " owner:1"]
)
def test_parse_actor_refuses_malformed(text):
    with pytest.raises(InvalidActor):
        parse_actor(text)
