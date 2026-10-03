import json
from datetime import date

import pytest

from app.domain.models import BankTxnNew, ReceivableNew, TaxObligationNew
from app.domain.states import ActorNotAllowed, AgentActorRefused, InvalidActor
from app.ledger import writer
from tests.ledger_helpers import events, fake_clock, make_ledger_db, payable_new

KW = dict(reason="test", source_ref="test:1")


@pytest.fixture
def conn(tmp_path):
    c = make_ledger_db(tmp_path / "ledger.db")
    yield c
    c.close()


# --- creation -------------------------------------------------------------


def test_create_payable_writes_draft_row_and_one_event(conn):
    p = writer.create_payable(payable_new(), actor="pipeline", conn=conn, clock=fake_clock(), **KW)

    assert p.status == "DRAFT" and p.version == 1 and p.amount_paise == 12_000_000
    evs = events(conn)
    assert len(evs) == 1
    ev = evs[0]
    assert (ev["event_type"], ev["entity"], ev["entity_id"], ev["actor"]) == (
        "PAYABLE_CREATED", "payable", p.id, "pipeline",
    )
    assert ev["business_id"] == 1
    assert ev["before_json"] is None
    assert json.loads(ev["after_json"])["amount_paise"] == 12_000_000
    assert ev["occurred_at"] == "2026-10-12T09:00:00+05:30"
    assert (ev["reason"], ev["source_ref"]) == ("test", "test:1")


def test_create_is_committed(conn):
    writer.create_payable(payable_new(), actor="owner:1", conn=conn, **KW)
    assert not conn.in_transaction


@pytest.mark.parametrize("actor", ["agent:case:1", "agent:"])
def test_agent_cannot_create_anything(conn, actor):
    with pytest.raises(AgentActorRefused):
        writer.create_payable(payable_new(), actor=actor, conn=conn, **KW)
    with pytest.raises(AgentActorRefused):
        writer.create_receivable(
            ReceivableNew(business_id=1, amount_paise=1, confidence="EXPECTED"),
            actor=actor, conn=conn, **KW,
        )
    with pytest.raises(AgentActorRefused):
        writer.create_bank_txn(
            BankTxnNew(account_id=1, direction="debit", amount_paise=1,
                       txn_date=date(2026, 10, 12), dedup_key="k", status="UNMATCHED"),
            actor=actor, conn=conn, **KW,
        )
    with pytest.raises(AgentActorRefused):
        writer.create_tax_obligation(_tax(), actor=actor, conn=conn, **KW)
    assert conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 0
    assert events(conn) == []


@pytest.mark.parametrize(
    "actor, error",
    [
        ("owner:2", ActorNotAllowed),   # a helper, not an owner
        ("owner:3", ActorNotAllowed),   # owner of a different business
        ("owner:99", ActorNotAllowed),  # no such user
        ("planner", ActorNotAllowed),   # role not allowed to create bills
        ("reconciler", ActorNotAllowed),
        ("seed", InvalidActor),
    ],
)
def test_create_payable_refuses_wrong_actors(conn, actor, error):
    with pytest.raises(error):
        writer.create_payable(payable_new(), actor=actor, conn=conn, **KW)
    assert events(conn) == []


def test_create_receivable_owner_only(conn):
    new = ReceivableNew(business_id=1, amount_paise=3_300_000,
                        expected_date=date(2026, 10, 13), confidence="COMMITTED")
    r = writer.create_receivable(new, actor="owner:1", conn=conn, **KW)
    assert r.confidence == "COMMITTED" and r.version == 1
    assert [e["event_type"] for e in events(conn)] == ["RECEIVABLE_CREATED"]
    with pytest.raises(ActorNotAllowed):
        writer.create_receivable(new, actor="pipeline", conn=conn, **KW)


def _txn(status, key="k1", account_id=1):
    return BankTxnNew(account_id=account_id, direction="debit", amount_paise=4_500_000,
                      txn_date=date(2026, 10, 15), dedup_key=key, status=status)


def test_create_bank_txn_rules(conn):
    t = writer.create_bank_txn(_txn("UNMATCHED"), actor="pipeline", conn=conn, **KW)
    assert t.status == "UNMATCHED"
    a = writer.create_bank_txn(_txn("ADJUSTMENT", "k2"), actor="owner:1", conn=conn, **KW)
    assert a.status == "ADJUSTMENT"
    ev = events(conn)
    assert [e["event_type"] for e in ev] == ["BANK_TXN_CREATED", "BANK_TXN_CREATED"]
    assert {e["business_id"] for e in ev} == {1}  # derived through bank_account
    # The owner may create an UNMATCHED txn when confirming an alert the checks
    # could not settle (batch 3 plan, Q6); a helper or the planner may not.
    o = writer.create_bank_txn(_txn("UNMATCHED", "k3"), actor="owner:1", conn=conn, **KW)
    assert o.status == "UNMATCHED"
    with pytest.raises(ActorNotAllowed):
        writer.create_bank_txn(_txn("UNMATCHED", "k6"), actor="planner", conn=conn, **KW)
    with pytest.raises(ActorNotAllowed):  # business 2's owner cannot either
        writer.create_bank_txn(_txn("UNMATCHED", "k7"), actor="owner:3", conn=conn, **KW)
    with pytest.raises(ActorNotAllowed):
        writer.create_bank_txn(_txn("ADJUSTMENT", "k4"), actor="pipeline", conn=conn, **KW)
    with pytest.raises(ActorNotAllowed):  # business 2's owner cannot write business 1's account
        writer.create_bank_txn(_txn("ADJUSTMENT", "k5"), actor="owner:3", conn=conn, **KW)


def _tax(**over):
    base = dict(business_id=1, tax_type="GST", period="2026-09", due_date=date(2026, 10, 20),
                amount_paise=9_000_000, amount_status="CONFIRMED")
    return TaxObligationNew(**{**base, **over})


def test_tax_obligation_creates_its_statutory_payable(conn):
    t = writer.create_tax_obligation(
        _tax(), invoice_number="GST-OCT26", actor="owner:1", conn=conn, **KW
    )

    p = conn.execute("SELECT * FROM payable WHERE id = ?", (t.payable_id,)).fetchone()
    assert (p["priority"], p["amount_paise"], p["due_date"], p["status"], p["invoice_number"]) == (
        "statutory", 9_000_000, "2026-10-20", "DRAFT", "GST-OCT26",
    )
    assert [e["event_type"] for e in events(conn)] == ["PAYABLE_CREATED", "TAX_OBLIGATION_CREATED"]


def test_second_obligation_links_to_an_existing_statutory_payable(conn):
    pf = writer.create_tax_obligation(
        _tax(tax_type="PF", amount_paise=3_600_000, amount_status="ESTIMATED",
             due_date=date(2026, 10, 15)),
        invoice_number="PFESI-OCT26", payable_amount_paise=4_500_000,
        actor="owner:1", conn=conn, **KW,
    )
    esi = writer.create_tax_obligation(
        _tax(tax_type="ESI", amount_paise=900_000, amount_status="ESTIMATED",
             due_date=date(2026, 10, 15)),
        payable_id=pf.payable_id, actor="owner:1", conn=conn, **KW,
    )
    assert esi.payable_id == pf.payable_id
    assert conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 1
    assert conn.execute("SELECT amount_paise FROM payable").fetchone()[0] == 4_500_000


def test_linking_refuses_a_non_statutory_or_foreign_payable(conn):
    normal = writer.create_payable(payable_new(), actor="owner:1", conn=conn, **KW)
    with pytest.raises(ValueError):
        writer.create_tax_obligation(_tax(), payable_id=normal.id, actor="owner:1", conn=conn, **KW)
    other = writer.create_tax_obligation(_tax(business_id=2), actor="owner:3", conn=conn, **KW)
    with pytest.raises(ValueError):
        writer.create_tax_obligation(
            _tax(), payable_id=other.payable_id, actor="owner:1", conn=conn, **KW
        )


def test_a_missing_amount_obligation_has_no_payable_and_asks_the_owner(conn):
    # D11 (batch 1 verdict), landed with CHG-007: the planner never invents an amount.
    ob = writer.create_tax_obligation(_tax(amount_paise=None, amount_status="MISSING"), actor="owner:1",
                                      conn=conn, **KW)
    assert ob.payable_id is None and conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 0
    q = conn.execute("SELECT kind, choices_json FROM owner_question").fetchone()
    assert q[0] == "ca_reminder" and q[1] == f'{{"tax_obligation_id": {ob.id}}}'
    with pytest.raises(ValueError, match="D11"):
        writer.create_tax_obligation(_tax(amount_paise=None, amount_status="MISSING"), actor="owner:1",
                                     conn=conn, payable_amount_paise=100, **KW)


@pytest.mark.parametrize("bad", [4_500_000.5, 4_500_000.0, True, 0, -1, "4500000"])
def test_combined_payable_amount_must_be_positive_int_paise(conn, bad):
    with pytest.raises(TypeError):
        writer.create_tax_obligation(_tax(), payable_amount_paise=bad, actor="owner:1", conn=conn, **KW)
    assert conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 0


def test_combined_payable_amount_cannot_be_given_when_linking(conn):
    first = writer.create_tax_obligation(_tax(), actor="owner:1", conn=conn, **KW)
    with pytest.raises(ValueError):
        writer.create_tax_obligation(_tax(tax_type="TDS"), payable_id=first.payable_id,
                                     payable_amount_paise=100, actor="owner:1", conn=conn, **KW)


def test_writer_refuses_a_connection_without_foreign_keys(tmp_path):
    import sqlite3

    make_ledger_db(tmp_path / "fk.db").close()
    bare = sqlite3.connect(tmp_path / "fk.db")
    bare.row_factory = sqlite3.Row
    with pytest.raises(RuntimeError, match="foreign_keys"):
        writer.create_payable(payable_new(), actor="owner:1", conn=bare, **KW)
    bare.close()
