---
id: CHG-031
title: The agent can finish a drift case when the evidence is in the mailbox
type: defect
lane: planned
---

## Context
This was found by the first live run (`docs/evals/2026-10-04-live-pilot/`, scenario 07) and diagnosed from its kept trace (`traces/07-missed-alert-causes-drift-run1/`, job 11):
- The agent found the missed alert and named it as the ₹20,000 gap.
- Its add_candidate `fields` used names of its own, because neither the prompt nor the tool says which fields a bank_alert record has. The tool replied "9 field error(s): Field required", naming none of them.
- The agent then gave a RESOLVED answer relying on no candidate. Code accepted it, the gap stayed open, and the account went to ASK_OWNER.
- The stored message was handed on to the pipeline. The pipeline wrote the debit with the document as its source, not the case (D21).

## Description
Fix the cause in the harness: the prompt, the tool's replies, the code's check of a final answer, the case facts and provenance. Nothing hard-codes the answer. Asking the owner when the evidence isn't in the mailbox stays allowed and safe.

## Acceptance Criteria
Batch 8 plan, docs/batches/2026-10-04-8/plan.md:
- [ ] AC1: the prompt lists add_candidate's fields per record type, generated from the extract schemas, and a test keeps the two in step. The prompt tells the agent to fix a refused call and retry within its limits, and, for a drift case, to search by the account's alert sender and the date window.
- [ ] AC2: a schema refusal names every missing and unexpected field, and the expected ones.
- [ ] AC3: a drift case's RESOLVED answer that relies on no VALID bank_alert candidate is refused, and the run goes on within its limits.
- [ ] AC4: a drift case's facts name the account's alert sender, the gap amount and the date window.
- [ ] AC5: a message the agent stored and handed on to the pipeline is written with the case in its source (`agent:case:<id>`).
- [ ] AC6: a fixture replay of the live trace's mistake (wrong field names, then the right ones) resolves the case at medium.

## History
- 2026-10-04: found by the live pilot; PO folded it into batch 8
