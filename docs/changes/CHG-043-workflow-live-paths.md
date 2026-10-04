---
id: CHG-043
title: Workflow B's scripted owner finds a debit by amount and date, and picks an offered choice by a stated rule
type: defect
lane: direct
---

## Context
Live workflow B (`docs/evals/workflow-B-2026-10-04-live.md`) failed where the live model left the script's
canned path: a statement's ₹590 row came back with no counterparty, so the scripted owner (who looked the
question up by that text) found none; and the agent offered its own choices for the ₹12,500 debit, so the
canned button wasn't there.

## Acceptance Criteria (PO)
- [ ] AC1: the scripted owner finds a debit's question by amount (and date when given), never by counterparty
  text; more than one match fails the step.
- [ ] AC2: an agent question is answered by a rule written into the step (the one offered choice containing a
  keyword); none or several fail the step with "choice not offered" and the choices. Never a guess.
- [ ] AC3: the live model's deviations stay visible in the report: the extraction check on the statement rows
  is unchanged, and the pressed choice is recorded.

## History
- 2026-10-04: from live workflow B and the PO; batch 15 (direct lane)
