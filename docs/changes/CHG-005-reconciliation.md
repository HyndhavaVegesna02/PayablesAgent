---
id: CHG-005
title: Reconciliation — matching, failures, reversals, drift check
type: feature
lane:
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
- [ ] AC1: An approved payment plus a matching debit alert moves the bill to PAID
- [ ] AC2: A return/failure email moves the bill to REOPENED and the original debit to REVERSED
- [ ] AC3: A missing alert produces a CHECKING drift state, and the agent recovering the transaction from Gmail closes the gap
- [ ] AC4: While drift is unresolved, every planner snapshot uses the lower of the two balances

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 4
- 2026-10-02: PO leanings from batch 1's Q5/Q6. Settle these when CHG-005 is planned; until then the moves are refused.
  - UNMATCHED→EXPLAINED: owner only. The TDD has the agent ask the owner what an unexpected transaction was.
  - UNMATCHED→MATCHED: allowed for the owner when they resolve a REVIEW bill as paid against a specific transaction.
  - UNMATCHED→REVERSED: reconciler only, for a failure email whose debit was never matched.
  - Receivables: the owner may re-rate among COMMITTED/EXPECTED/UNKNOWN. Creation is by the owner only (via confirm_record), never by the pipeline. CONFIRMED→anything else is out of the MVP.
