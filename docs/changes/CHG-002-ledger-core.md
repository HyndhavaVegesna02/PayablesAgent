---
id: CHG-002
title: Ledger core — domain models, ledger writer, transition table, event triggers
type: feature
lane: planned
---

## Context
TDD Part 2, MVP build sequence, Phase 1. Owner: person B. Depends on CHG-001 (schema must exist).
Plan: docs/batches/2026-10-02-1/plan.md. Lane `planned`; trigger: migrates or deletes data (D3).

## Description
This change adds four modules:
- `app/domain/money.py`: the lakh formatter.
- `app/domain/models.py`: Pydantic models for ledger records, with StrictInt paise.
- `app/domain/states.py`: the Part 2 transition table, the D2 tables for bank_txn and receivable, and actor parsing.
- `app/ledger/writer.py`: implements `transition(entity, to_state, actor, reason, source_ref)`.

`transition()` is the only function that writes ledger tables or the state of a payable, receivable or transaction. It bumps `version` and writes the `event` row in the same transaction. Any actor starting with `agent:` is refused for every transition. The seed now goes through the writer.

## PO decisions (2026-10-02, payablesagent-ac)
- D2: bank_txn.status and receivable.confidence get allowed-transition tables. Every row cites the TDD. Uncited moves are questions and are refused until answered. `agent:` is refused for all of them.
- D3: the seed leaves an audit trail.
  - Ledger records go through the writer.
  - tax_obligation rows are linked to their statutory payables (PF/ESI ESTIMATED, GST CONFIRMED).
  - A reseed recreates the DB file instead of deleting rows.
- D4: "only writer.py writes ledger tables" is enforced mechanically by a static test.
- D5: the "PAID never disappears" invariant belongs to the writer, and is tested with a Hypothesis stateful test.
- D7: an import-linter contract stops app.ledger from importing app.ai, app.agent, app.web or app.ingest.

## Acceptance Criteria
- [ ] AC1: A transition or create attempted by an `agent:*` actor is refused for every entity and every state.
- [ ] AC2: Every transition in Part 2's table succeeds for its allowed actor, and is refused for any other actor. Any move not in the table is refused.
- [ ] AC3: A successful transition bumps `version` and writes exactly one `event` row in the same DB transaction. An injected failure after the UPDATE rolls back both.
- [ ] AC4: Updating or deleting an `event` row raises. This exercises the CHG-001 triggers, not just their creation.
- [ ] AC5: A Hypothesis stateful test drives random transition sequences through `transition()`. Rows are never deleted, and a PAID bill only ever leaves to REOPENED (D5).
- [ ] AC6: The D4 write-guard test exists and passes. It fails if any SQL outside app/ledger/writer.py writes to payable, receivable, bank_txn, tax_obligation or event. Migrations are exempt, and every allow-list entry needs a reason.
- [ ] AC7: The seed goes through the writer (D3).
  - It creates tax_obligation rows linked to their statutory payables via payable_id: PF/ESI ESTIMATED, GST CONFIRMED.
  - Every ledger row has its creation event.
- [ ] AC8: Owner actions must pass the version the owner saw. A stale or missing version is refused, and nothing is written.
- [ ] AC9: SPLIT works atomically through the writer.
  - Only the owner can split, and only from CONFIRMED or PLANNED.
  - The parent is marked SPLIT, and two child payables are created with parent_payable_id.
- [ ] AC10: Money is int paise throughout.
  - format_inr uses lakh grouping: "₹2,82,000", "₹1,83,000".
  - It refuses float and bool.
- [ ] AC11: The D2 transition tables for bank_txn and receivable are enforced. Cited rows succeed, and uncited moves are refused.
- [ ] AC12: The D7 import-linter contract exists and is kept.

## Expected paths
- app/domain/money.py
- app/domain/states.py
- app/domain/models.py
- app/ledger/__init__.py
- app/ledger/writer.py
- fixtures/seed.py
- Makefile
- pyproject.toml
- CLAUDE.md
- tests/test_money.py
- tests/test_states.py
- tests/test_models.py
- tests/test_ledger_writer.py
- tests/test_ledger_writer_stateful.py
- tests/test_ledger_write_guard.py
- tests/test_seed.py

## Open Questions
- Answered at batch 1 verdict: MISSING tax amounts stay refused here; the design (D11) lands in CHG-007.

Answered by the PO on 2026-10-02:
- Q1: the seed creates `app_user` 1, an owner whose sentinel hash can never verify.
- Q2: one PFESI payable, linked to PF ₹36,000 and ESI ₹9,000. Both obligations are ESTIMATED, and the split is fixture-invented.
- Q5/Q6: deferred to CHG-005. Those moves stay refused until then.
- Q7: payables are created in DRAFT by the pipeline or the owner. Split children start CONFIRMED.
- Event names: `<ENTITY>_<TO_STATE>`, `<ENTITY>_CREATED`, `PAYABLE_SPLIT`.
- D10: the write guard also flags UPDATE and DELETE on bank_account outside writer.py. INSERT stays allowed for setup and seed.

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 1
- 2026-10-02: refined for batch 1 with PO decisions D2–D5 and D7; AC5–AC12 added
- 2026-10-02: batch 1 fix round 1 (review FIX_REQUIRED). Two rigged tests un-rigged, dead code removed, payable_amount_paise must be positive int paise, PayableNew refuses discount >= amount or unpaired discount fields. Two deviations recorded: (1) create_tax_obligation REFUSES a MISSING amount; it no longer creates an obligation with no payable. How a MISSING tax amount is tracked is an open question for the PO (the TDD has every obligation create a payable, and a payable needs an amount). (2) PAYABLE_SPLIT carries the caller's source_ref (e.g. shortfall_option:1); the two child PAYABLE_CREATED events carry payable:<parent id>.
- 2026-10-02: ACCEPTED at batch 1 verdict (PO). MISSING tax amounts: refusal kept; the final design is D11, recorded in CHG-007.
