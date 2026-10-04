---
id: CHG-034
title: The eval's scripted owner fills every field the page marks (PO D28.2)
type: defect
lane: direct
---

## Context
In the same run the entry reached the owner with its amount marked as unreadable; the scripted owner only filled a missing due date, so the form refused the empty amount.

## Acceptance Criteria
Batch 10 plan, docs/batches/2026-10-04-10/plan.md:
- [ ] AC1: Needs attention marks every required field of a waiting bill or sales invoice that is empty (vendor or customer, amount, and a bill's due date), not only a missing due date.
- [ ] AC2: the scripted owner (evals/runner.py and the workflow runs) fills every marked field with the value the document or transcript gives, which the scenario states; a marked field the scenario gives no value for is a scenario error, not a model failure.
- [ ] AC3: an owner-form refusal remains possible only when the owner's own input is invalid.

## History
- 2026-10-04: planned for batch 10 (direct lane)
