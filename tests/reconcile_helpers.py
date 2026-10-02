"""Seeded worked example plus helpers to approve bills and write bank
transactions the way the pipeline does, for reconciliation tests."""

from __future__ import annotations

from datetime import date

from app.domain.models import BankTxnNew
from app.jobs.replan import replan
from app.ledger import writer
from app.ledger.writer import EntityRef

PAPER, PFESI, ELEC, GST, PRIME = 1, 2, 3, 4, 5
KAVERI, NANDI = 1, 2  # receivable ids


def plan_and_approve(env, *bill_ids: int) -> None:
    """Runs a replan (bills 1-4 become PLANNED) and has the owner approve these."""
    replan(env.conn, 1, triggered_by="test", clock=env.clock)
    for bill_id in bill_ids:
        v = env.conn.execute("SELECT version FROM payable WHERE id = ?", (bill_id,)).fetchone()[0]
        writer.transition(EntityRef("payable", bill_id), "PAYMENT_EXPECTED", "owner:1", "approved", None,
                          conn=env.conn, expected_version=v, clock=env.clock)


_keys = iter(range(1, 10_000))


def txn(env, direction: str, paise: int, day: date, counterparty: str | None, reference: str | None = None,
        *, balance: int | None = None) -> int:
    t = writer.create_bank_txn(
        BankTxnNew(account_id=1, direction=direction, amount_paise=paise, txn_date=day,
                   counterparty=counterparty, reference=reference, balance_after_paise=balance,
                   dedup_key=f"test:{next(_keys)}", status="UNMATCHED"),
        actor="pipeline", reason="test alert", source_ref=None, conn=env.conn, clock=env.clock,
    )
    return t.id


def status(env, table: str, row_id: int) -> str:
    col = "confidence" if table == "receivable" else "status"
    return env.conn.execute(f"SELECT {col} FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]


def cases(env):
    return env.conn.execute("SELECT * FROM agent_case ORDER BY id").fetchall()
