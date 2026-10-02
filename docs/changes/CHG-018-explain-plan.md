---
id: CHG-018
title: explain_plan job — plan diff to a plain-language summary (Gemini), number check, template fallback
type: feature
lane:
---

## Context
Batch 2 plan, Q9. CHG-013's replan persists plans but queues no `explain_plan` job, because nothing handles it yet. The TDD's replan flow ends with an explanation of what changed for the owner. Depends on CHG-013 (persisted plan runs) and CHG-004 (`ai.client`).

## Description
- `explain_plan` job: takes the previous and current `plan_run`, runs `app/planner/diff.py`, and asks Gemini (through `ai.client`) for a short summary of the changes.
- Code checks every number in the summary against the diff (amounts and dates on the allow-lists); any mismatch drops the model text and uses a template built from the diff.
- Queued by `handle_replan` once this lands.

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from batch 2 plan Q9 (explain_plan has no handler in batch 2)
