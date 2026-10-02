---
id: CHG-005
title: Reconciliation — matching, failures, reversals, drift check
type: feature
lane: planned
---

## Context
TDD Part 2, MVP build sequence, Phase 4. Owner: person B. Depends on CHG-002, CHG-003, CHG-004.
This is the first joint checkpoint per the TDD: a test-inbox debit alert reconciles
against a payment approved through the planner.

## Description
`app/ledger/reconcile.py` — matching (Part 2, "Reconciliation and drift"), failure/
reversal handling, and the drift check's three-step procedure (spot the gap, recheck
Gmail, ask the owner).

## Acceptance Criteria
Batch 2 plan, docs/batches/2026-10-02-2/plan.md (these replace the drafted ones).

- [ ] AC1: An approved payment plus a matching debit alert moves the bill to PAID and the debit to MATCHED, atomically, and queues a replan.
- [ ] AC2: A return or failure email moves the bill to REOPENED and its original debit to REVERSED, then queues a replan. A failure that matches no bill opens a `failed_payment` case.
- [ ] AC3: An ambiguous debit (no name match, or several candidates) moves the bill or bills to REVIEW and opens an `ambiguous_match` case. A debit matching nothing stays UNMATCHED with an `unknown_txn` case. Cases start at high thinking when the stake exceeds the escalation amount.
- [ ] AC4: A credit matching an open receivable marks it CONFIRMED. A name match with a different amount opens a case.
- [ ] AC5: Drift:
  - An alert's available balance that disagrees is rechecked at 23:00. A mismatch that remains sets the account to CHECKING and opens a drift case. A statement mismatch is acted on at once.
  - A later transaction that closes the gap returns the account to OK.
  - `confirm_balance` writes an ADJUSTMENT txn with the owner as actor and returns the account to OK.
- [ ] AC6: While drift is unresolved, every planner snapshot uses the lower of the two balances. This is shown through the persisted replan, not only through the planner.
- [ ] AC7: Every bank_account and ledger change in this change goes through the writer. The guard (R008) is green, and agent actors are refused for the drift moves.
- [ ] AC8: The Phase 4 exit test runs all three scenarios end to end through the worker on the seeded DB with the fake AI. It also shows the debit's trace.
- [ ] AC9: Re-delivering the same debit alert (a second `.eml` copy of it, or the same message seen twice) leaves exactly one `bank_txn` and one match. It is stopped by `bank_txn.dedup_key` and the `source_document` unique keys (PO addition).

## Expected paths
- `app/ledger/reconcile.py`
- `app/ledger/writer.py`
- `app/domain/states.py`
- `app/jobs/`
- `app/worker.py`
- `app/ingest/pipeline.py`
- `tests/test_reconcile_match.py`
- `tests/test_reconcile_failure.py`
- `tests/test_drift.py`
- `tests/test_phase4_exit.py`
- `tests/test_states.py`
- `tests/test_ledger_transitions.py`

## Open Questions
None. PO accepted every default on 2026-10-02 (see the plan's PO decisions).

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 4
- 2026-10-02: PO leanings from batch 1's Q5/Q6. Settle these when CHG-005 is planned; until then the moves are refused.
  - UNMATCHED→EXPLAINED: owner only. The TDD has the agent ask the owner what an unexpected transaction was.
  - UNMATCHED→MATCHED: allowed for the owner when they resolve a REVIEW bill as paid against a specific transaction.
  - UNMATCHED→REVERSED: reconciler only, for a failure email whose debit was never matched.
  - Receivables: the owner may re-rate among COMMITTED/EXPECTED/UNKNOWN. Creation is by the owner only (via confirm_record), never by the pipeline. CONFIRMED→anything else is out of the MVP.
- 2026-10-02: planned for batch 2 (lane planned, cap: consumes CHG-004's extract contract). ACs rewritten in the plan. Original AC3's "the agent recovering the transaction from Gmail closes the gap" splits: the code side (a later txn closes the gap, CHECKING→OK) lands here; the agent's Gmail search lands with CHG-008 (Q13). PO leaning UNMATCHED→REVERSED lands here; the other leaned rows land with their callers (Q7).
- 2026-10-02: PO approved the batch 2 plan; status ready, batch 2.
- 2026-10-03: as built, after review rounds 1-2: report times compared as instants and stored in IST; unknown and ambiguous debits replan; a reversal while CHECKING rechecks the gap; failure notices become ACCEPTED once reconciled; cases are deduplicated only for per-event subjects (bank_txn:, candidate:), and a gap that closes resolves its drift case, so each drift episode gets its own case.
