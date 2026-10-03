import json
import sqlite3
from datetime import date

import pytest

from app.domain.models import BankTxnNew, ReceivableNew
from app.domain.states import (
    PAYABLE_STATES,
    PAYABLE_TRANSITIONS,
    ActorNotAllowed,
    AgentActorRefused,
    FieldNotAllowed,
    IllegalTransition,
    RecordNotFound,
    StaleVersion,
    TransitionRefused,
    VersionRequired,
)
from app.ledger import writer
from app.ledger.writer import EntityRef
from tests.ledger_helpers import events, fake_clock, make_ledger_db

KW = dict(reason="test", source_ref="test:1")
ROLES = {"owner": "owner:1", "planner": "planner", "reconciler": "reconciler", "pipeline": "pipeline"}


@pytest.fixture
def conn(tmp_path):
    c = make_ledger_db(tmp_path / "ledger.db")
    yield c
    c.close()


def _payable_in(conn, status, planned_date="2026-10-22"):
    """Test setup only: place a payable directly in `status` (tests are exempt from the write guard)."""
    cur = conn.execute(
        "INSERT INTO payable (business_id, amount_paise, due_date, priority, status, planned_date) "
        "VALUES (1, 12000000, '2026-10-22', 'normal', ?, ?)",
        (status, planned_date if status != "DRAFT" else None),
    )
    conn.commit()
    return EntityRef("payable", cur.lastrowid)


def _row(conn, ref):
    table = ref.kind
    return dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (ref.id,)).fetchone())


def _fields_for(to_state):
    return {"planned_date": date(2026, 10, 22)} if to_state == "PLANNED" else None


# --- S5: the full payable matrix --------------------------------------------


def test_every_payable_move_matches_the_part2_table(conn):
    checked = 0
    for frm in PAYABLE_STATES:
        for to in PAYABLE_STATES:
            if to == "SPLIT":
                continue
            for role, actor in ROLES.items():
                ref = _payable_in(conn, frm)
                before = _row(conn, ref)
                n_events = len(events(conn))
                allowed = role in PAYABLE_TRANSITIONS.get((frm, to), frozenset())
                call = lambda: writer.transition(  # noqa: E731
                    ref, to, actor, "test", "test:1", conn=conn, expected_version=1,
                    fields=_fields_for(to), clock=fake_clock(),
                )
                if allowed:
                    p = call()
                    assert (p.status, p.version) == (to, 2), (frm, to, role)
                    evs = events(conn)
                    assert len(evs) == n_events + 1
                    ev = evs[-1]
                    assert ev["event_type"] == f"PAYABLE_{to}"
                    assert json.loads(ev["before_json"])["status"] == frm
                    assert json.loads(ev["after_json"])["status"] == to
                    assert ev["actor"] == actor
                else:
                    with pytest.raises((IllegalTransition, ActorNotAllowed)):
                        call()
                    assert _row(conn, ref) == before, (frm, to, role)
                    assert len(events(conn)) == n_events
                checked += 1
    assert checked == 8 * 7 * 4


@pytest.mark.parametrize("frm", PAYABLE_STATES)
def test_agent_refused_for_every_payable_move(conn, frm):
    ref = _payable_in(conn, frm)
    for to in PAYABLE_STATES:
        with pytest.raises(AgentActorRefused):
            writer.transition(ref, to, "agent:case:7", "x", None, conn=conn, expected_version=1,
                              fields=_fields_for(to))
    assert events(conn) == []


def test_split_is_not_reachable_through_transition(conn):
    ref = _payable_in(conn, "CONFIRMED")
    with pytest.raises(IllegalTransition, match="split_payable"):
        writer.transition(ref, "SPLIT", "owner:1", "x", None, conn=conn, expected_version=1)


def test_unknown_entity_kind_is_a_named_refusal(conn):
    with pytest.raises(IllegalTransition):
        writer.transition(EntityRef("tax_obligation", 1), "CONFIRMED", "owner:1", "x", None,
                          conn=conn, expected_version=1)


def test_missing_record(conn):
    with pytest.raises(RecordNotFound):
        writer.transition(EntityRef("payable", 999), "PLANNED", "planner", "x", None, conn=conn,
                          fields={"planned_date": date(2026, 10, 22)})


def test_owner_of_another_business_cannot_move_a_bill(conn):
    ref = _payable_in(conn, "DRAFT")
    with pytest.raises(ActorNotAllowed):
        writer.transition(ref, "CONFIRMED", "owner:3", "x", None, conn=conn, expected_version=1)
    with pytest.raises(ActorNotAllowed):  # a helper's id is not an owner
        writer.transition(ref, "CONFIRMED", "owner:2", "x", None, conn=conn, expected_version=1)


def test_event_rows_stay_append_only_after_a_transition(conn):
    ref = _payable_in(conn, "DRAFT")
    writer.transition(ref, "CONFIRMED", "owner:1", "x", None, conn=conn, expected_version=1)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE event SET reason = 'edited'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM event")
    conn.rollback()


# --- S6: one transaction -----------------------------------------------------


def test_failure_after_the_update_rolls_back_version_state_and_event(conn, monkeypatch):
    ref = _payable_in(conn, "DRAFT")
    before = _row(conn, ref)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(writer, "_insert_event", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        writer.transition(ref, "CONFIRMED", "owner:1", "x", None, conn=conn, expected_version=1)

    assert _row(conn, ref) == before
    assert events(conn) == []
    assert not conn.in_transaction


def test_atomic_groups_writer_calls(conn):
    a = _payable_in(conn, "DRAFT")
    b = _payable_in(conn, "DRAFT")
    with pytest.raises(StaleVersion):
        with writer.atomic(conn):
            writer.transition(a, "CONFIRMED", "owner:1", "x", None, conn=conn, expected_version=1)
            writer.transition(b, "CONFIRMED", "owner:1", "x", None, conn=conn, expected_version=9)
    assert _row(conn, a)["status"] == "DRAFT"
    assert events(conn) == []


def test_inside_a_caller_transaction_the_writer_uses_a_savepoint(conn):
    a = _payable_in(conn, "DRAFT")
    conn.execute("UPDATE job SET status = status")  # opens an implicit transaction
    assert conn.in_transaction
    with pytest.raises(StaleVersion):
        writer.transition(a, "CONFIRMED", "owner:1", "x", None, conn=conn, expected_version=5)
    assert conn.in_transaction  # the caller's transaction survives the refusal
    writer.transition(a, "CONFIRMED", "owner:1", "x", None, conn=conn, expected_version=1)
    conn.commit()
    assert _row(conn, a)["status"] == "CONFIRMED"


# --- S7: optimistic locking --------------------------------------------------


def test_owner_must_pass_the_version_they_saw(conn):
    ref = _payable_in(conn, "DRAFT")
    with pytest.raises(VersionRequired):
        writer.transition(ref, "CONFIRMED", "owner:1", "x", None, conn=conn)
    with pytest.raises(StaleVersion):
        writer.transition(ref, "CONFIRMED", "owner:1", "x", None, conn=conn, expected_version=0)
    assert _row(conn, ref)["version"] == 1
    assert events(conn) == []


def test_second_owner_action_on_the_same_version_is_refused(conn):
    ref = _payable_in(conn, "PLANNED")
    writer.transition(ref, "PAYMENT_EXPECTED", "owner:1", "x", None, conn=conn, expected_version=1)
    before = _row(conn, ref)
    with pytest.raises(StaleVersion):  # the owner's page still shows version 1
        writer.transition(ref, "PAID", "owner:1", "x", None, conn=conn, expected_version=1)
    assert _row(conn, ref) == before
    assert len(events(conn)) == 1


def test_system_actor_may_omit_version_but_not_pass_a_stale_one(conn):
    ref = _payable_in(conn, "CONFIRMED")
    writer.transition(ref, "PLANNED", "planner", "x", None, conn=conn,
                      fields={"planned_date": date(2026, 10, 22)})
    with pytest.raises(StaleVersion):
        writer.transition(ref, "CONFIRMED", "planner", "x", None, conn=conn, expected_version=1)


# --- S8: fields set alongside a move -----------------------------------------


def test_planned_requires_a_planned_date(conn):
    ref = _payable_in(conn, "CONFIRMED", planned_date=None)
    with pytest.raises(FieldNotAllowed):
        writer.transition(ref, "PLANNED", "planner", "x", None, conn=conn)
    with pytest.raises(TypeError):
        writer.transition(ref, "PLANNED", "planner", "x", None, conn=conn,
                          fields={"planned_date": "2026-10-22"})
    p = writer.transition(ref, "PLANNED", "planner", "x", None, conn=conn,
                          fields={"planned_date": date(2026, 10, 19)})
    assert p.planned_date == date(2026, 10, 19)


def test_replan_to_wait_clears_the_planned_date(conn):
    ref = _payable_in(conn, "PLANNED")
    p = writer.transition(ref, "CONFIRMED", "planner", "x", None, conn=conn)
    assert p.planned_date is None


def test_approval_records_who_and_when(conn):
    ref = _payable_in(conn, "PLANNED")
    p = writer.transition(ref, "PAYMENT_EXPECTED", "owner:1", "approve", None, conn=conn,
                          expected_version=1, clock=fake_clock())
    assert p.approved_by == 1
    assert p.approved_at == "2026-10-12T09:00:00+05:30"


def test_paid_may_carry_the_matched_txn(conn):
    txn = writer.create_bank_txn(
        BankTxnNew(account_id=1, direction="debit", amount_paise=12_000_000,
                   txn_date=date(2026, 10, 22), dedup_key="d1", status="UNMATCHED"),
        actor="pipeline", conn=conn, **KW,
    )
    ref = _payable_in(conn, "PAYMENT_EXPECTED")
    p = writer.transition(ref, "PAID", "reconciler", "matched", f"bank_txn:{txn.id}", conn=conn,
                          fields={"matched_txn_id": txn.id})
    assert p.matched_txn_id == txn.id


@pytest.mark.parametrize("field", ["amount_paise", "status", "version", "due_date", "approved_by"])
def test_other_fields_are_refused(conn, field):
    ref = _payable_in(conn, "PAYMENT_EXPECTED")
    with pytest.raises(FieldNotAllowed):
        writer.transition(ref, "PAID", "reconciler", "x", None, conn=conn, fields={field: 1})


# --- S9: bank_txn and receivable (D2) ----------------------------------------


def _txn(conn, key="t1"):
    t = writer.create_bank_txn(
        BankTxnNew(account_id=1, direction="credit", amount_paise=20_000_000,
                   txn_date=date(2026, 10, 16), dedup_key=key, status="UNMATCHED"),
        actor="pipeline", conn=conn, **KW,
    )
    return EntityRef("bank_txn", t.id)


def test_bank_txn_cited_moves(conn):
    ref = _txn(conn)
    t = writer.transition(ref, "MATCHED", "reconciler", "x", None, conn=conn, fields={"party_id": None})
    assert t.status == "MATCHED"
    t = writer.transition(ref, "REVERSED", "reconciler", "x", None, conn=conn)
    assert t.status == "REVERSED"
    assert [e["event_type"] for e in events(conn, "bank_txn", ref.id)] == [
        "BANK_TXN_CREATED", "BANK_TXN_MATCHED", "BANK_TXN_REVERSED",
    ]


def test_a_never_matched_debit_can_be_reversed_by_the_reconciler(conn):
    ref = _txn(conn)
    t = writer.transition(ref, "REVERSED", "reconciler", "returned", "candidate:3", conn=conn)
    assert t.status == "REVERSED"
    assert [e["event_type"] for e in events(conn, "bank_txn", ref.id)] == [
        "BANK_TXN_CREATED", "BANK_TXN_REVERSED",
    ]


@pytest.mark.parametrize(
    "to, actor",
    [
        ("EXPLAINED", "owner:1"),    # Q5(a): deferred to CHG-005
        ("MATCHED", "owner:3"),      # the owner may match (batch 4, CHG-022 Q2), but not another business's txn
        ("REVERSED", "pipeline"),    # UNMATCHED -> REVERSED is the reconciler's (batch 2, Q7)
        ("REVERSED", "owner:1"),
        ("MATCHED", "pipeline"),
        ("ADJUSTMENT", "owner:1"),
    ],
)
def test_bank_txn_uncited_moves_are_refused(conn, to, actor):
    ref = _txn(conn)
    with pytest.raises(TransitionRefused):
        writer.transition(ref, to, actor, "x", None, conn=conn, expected_version=1)
    assert _row(conn, ref)["status"] == "UNMATCHED"


def test_the_owner_matches_a_debit_the_reconciler_could_not(conn):
    # Batch 4 plan, CHG-022 Q2: "this debit paid that bill" moves the txn as the owner.
    ref = _txn(conn)
    writer.transition(ref, "MATCHED", "owner:1", "owner: this paid bill 1", None, conn=conn)
    assert _row(conn, ref)["status"] == "MATCHED"


def test_agent_refused_for_bank_txn_and_receivable(conn):
    ref = _txn(conn)
    with pytest.raises(AgentActorRefused):
        writer.transition(ref, "MATCHED", "agent:case:1", "x", None, conn=conn)
    r = writer.create_receivable(
        ReceivableNew(business_id=1, amount_paise=20_000_000, confidence="EXPECTED"),
        actor="owner:1", conn=conn, **KW,
    )
    with pytest.raises(AgentActorRefused):
        writer.transition(EntityRef("receivable", r.id), "CONFIRMED", "agent:case:1", "x", None, conn=conn)


def test_receivable_confirmed_by_a_matched_credit(conn):
    txn = _txn(conn)
    r = writer.create_receivable(
        ReceivableNew(business_id=1, amount_paise=20_000_000, expected_date=date(2026, 10, 28),
                      confidence="EXPECTED"),
        actor="owner:1", conn=conn, **KW,
    )
    ref = EntityRef("receivable", r.id)
    out = writer.transition(ref, "CONFIRMED", "reconciler", "credit matched", None, conn=conn,
                            fields={"matched_txn_id": txn.id})
    assert (out.confidence, out.version, out.matched_txn_id) == ("CONFIRMED", 2, txn.id)
    assert events(conn, "receivable", r.id)[-1]["event_type"] == "RECEIVABLE_CONFIRMED"


@pytest.mark.parametrize(
    "start, to, actor",
    [
        ("COMMITTED", "EXPECTED", "owner:1"),  # Q6: owner re-rating deferred
        ("EXPECTED", "COMMITTED", "owner:1"),
        ("EXPECTED", "CONFIRMED", "owner:1"),
        ("CONFIRMED", "EXPECTED", "reconciler"),
    ],
)
def test_receivable_uncited_moves_are_refused(conn, start, to, actor):
    cur = conn.execute(
        "INSERT INTO receivable (business_id, amount_paise, confidence) VALUES (1, 100, ?)", (start,)
    )
    conn.commit()
    ref = EntityRef("receivable", cur.lastrowid)
    before = _row(conn, ref)
    with pytest.raises(TransitionRefused):
        writer.transition(ref, to, actor, "x", None, conn=conn, expected_version=1)
    assert _row(conn, ref) == before
    assert events(conn) == []


# --- S10: split ----------------------------------------------------------------


@pytest.mark.parametrize("start", ["CONFIRMED", "PLANNED"])
def test_split_makes_two_children_atomically(conn, start):
    ref = _payable_in(conn, start)
    first, second = writer.split_payable(
        ref, 5_300_000, date(2026, 10, 26), "owner:1", "owner chose split", "shortfall_option:1",
        conn=conn, expected_version=1,
    )
    parent = _row(conn, ref)
    assert (parent["status"], parent["version"]) == ("SPLIT", 2)
    assert (first.amount_paise, first.due_date) == (5_300_000, date(2026, 10, 22))
    assert (second.amount_paise, second.due_date) == (6_700_000, date(2026, 10, 26))
    for child in (first, second):
        assert child.parent_payable_id == ref.id
        assert child.status == "CONFIRMED"
        assert child.priority == "normal"
    assert first.amount_paise + second.amount_paise == parent["amount_paise"]
    evs = events(conn)
    assert [e["event_type"] for e in evs] == ["PAYABLE_SPLIT", "PAYABLE_CREATED", "PAYABLE_CREATED"]
    assert {e["source_ref"] for e in evs[1:]} == {f"payable:{ref.id}"}


@pytest.mark.parametrize("start", ["DRAFT", "PAYMENT_EXPECTED", "PAID", "REVIEW", "REOPENED", "SPLIT"])
def test_split_refused_from_other_states(conn, start):
    ref = _payable_in(conn, start)
    with pytest.raises(IllegalTransition):
        writer.split_payable(ref, 100, date(2026, 10, 26), "owner:1", "x", None, conn=conn,
                             expected_version=1)


def test_split_refuses_an_agent(conn):
    ref = _payable_in(conn, "CONFIRMED")
    with pytest.raises(AgentActorRefused):
        writer.split_payable(ref, 100, date(2026, 10, 26), "agent:case:1", "x", None, conn=conn,
                             expected_version=1)
    assert _row(conn, ref)["status"] == "CONFIRMED"


def test_split_is_atomic_when_the_second_child_fails(conn, monkeypatch):
    ref = _payable_in(conn, "CONFIRMED")
    real_create = writer._create
    calls = []

    def fail_on_second_child(conn_, table, values, **kw):
        if table == "payable":
            calls.append(values)
            if len(calls) == 2:
                raise RuntimeError("disk full")
        return real_create(conn_, table, values, **kw)

    monkeypatch.setattr(writer, "_create", fail_on_second_child)
    with pytest.raises(RuntimeError, match="disk full"):
        writer.split_payable(ref, 5_300_000, date(2026, 10, 26), "owner:1", "x", None, conn=conn,
                             expected_version=1)
    assert len(calls) == 2  # the first child was really written before the second failed
    assert (_row(conn, ref)["status"], _row(conn, ref)["version"]) == ("CONFIRMED", 1)
    assert conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 1
    assert events(conn) == []


@pytest.mark.parametrize("actor", ["planner", "reconciler", "pipeline", "owner:2"])
def test_split_is_owner_only(conn, actor):
    ref = _payable_in(conn, "CONFIRMED")
    with pytest.raises(ActorNotAllowed):
        writer.split_payable(ref, 100, date(2026, 10, 26), actor, "x", None, conn=conn,
                             expected_version=1)


@pytest.mark.parametrize(
    "first, second_due",
    [(0, date(2026, 10, 26)), (12_000_000, date(2026, 10, 26)), (-1, date(2026, 10, 26)),
     (100, date(2026, 10, 21))],
)
def test_split_refuses_bad_amounts_or_dates(conn, first, second_due):
    ref = _payable_in(conn, "CONFIRMED")
    with pytest.raises(ValueError):
        writer.split_payable(ref, first, second_due, "owner:1", "x", None, conn=conn,
                             expected_version=1)
    assert conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 1


def test_split_stale_version_writes_nothing(conn):
    ref = _payable_in(conn, "CONFIRMED")
    with pytest.raises(StaleVersion):
        writer.split_payable(ref, 100, date(2026, 10, 26), "owner:1", "x", None, conn=conn,
                             expected_version=7)
    assert conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 1
    assert events(conn) == []
