"""An exception case and its tool context for agent tests (batch 6, CHG-008)."""

from __future__ import annotations

from app.agent import cases
from app.agent.tools import ToolContext
from app.ingest.eml_folder import EmlFolderSource
from app.ledger.reconcile import open_case


def open_unknown_debit_case(env, stake_paise: int = 4_720_000) -> int:
    case_id = open_case(
        env.conn, 1, "unknown_txn", "bank_txn:1", stake_paise,
        goal="Find out what the ₹47,200 debit to APS PAPERS on Wed 14 Oct paid.",
        facts=["Debit ₹47,200 on Wed 14 Oct 2026 from account ending 4821", "Payee as written: APS PAPERS"],
        unknowns=["Which bill or vendor it paid"], clock=env.clock,
    )
    env.conn.commit()
    return case_id


def tool_context(env, case_id: int, step: int = 1) -> ToolContext:
    return ToolContext(conn=env.conn, db_path=env.settings.database_path, case=cases.load(env.conn, case_id),
                       mail=EmlFolderSource(env.settings.test_inbox_path, env.clock), clock=env.clock, step=step)
