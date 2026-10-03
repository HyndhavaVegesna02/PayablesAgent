---
id: CHG-024
title: Batch 4 review notes not fixed in the batch
type: chore
lane:
---

## Context
Non-blocking notes from the batch 4 review (docs/batches/2026-10-03-4/review.md, rounds 1-4). PO policy: non-blocking notes become backlog chores.

## Description
- An approved (PAYMENT_EXPECTED) authorised bill can lapse on a deeper breach. It has no plan line, so the D18 reason text shows nowhere, and the options come back with no explanation.
- `plan_override.breach_on` holds the day of the lowest balance, not the first breach day. Rename it or document it.
- CHG-021 changed what inputs_sha256 covers (overrides, then choice_id). Runs made before it go stale once after an upgrade, so the next approve replans first.
- No extra confirmation when a debit and the bill it pays differ by a large amount. The difference is shown only in the transition reason.
- The pending early_receipt `asked_note` is tested through `repo.options`, not through a rendered page.
- The "remember this name" checkbox on explain_txn shows even when the names already match. It is ignored there.
- D18 design limits: a later choice is measured on the plan with only the earlier kept choices. If an earlier choice lapsed or was undone, or a delay was chosen after an authorisation and moved a discount, that baseline is not exactly the plan the owner saw for it. Consider storing the no-authorisation low per choice if this matters.

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
