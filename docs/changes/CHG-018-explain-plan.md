---
id: CHG-018
title: explain_plan job — plan diff to a plain-language summary (Gemini), number check, template fallback
type: feature
lane: planned
---

## Context
Batch 2 plan, Q9. CHG-013's replan persists plans but queues no `explain_plan` job, because nothing handles it yet. The TDD's replan flow ends with an explanation of what changed for the owner. Depends on CHG-013 (persisted plan runs) and CHG-004 (`ai.client`).

## Description
- `explain_plan` job: takes the previous and current `plan_run`, runs `app/planner/diff.py`, and asks Gemini (through `ai.client`) for a short summary of the changes.
- Code checks every number in the summary against the diff (amounts and dates on the allow-lists); any mismatch drops the model text and uses a template built from the diff.
- Queued by `handle_replan` once this lands.

## Acceptance Criteria
Batch 6 plan, docs/batches/2026-10-03-6/plan.md ("CHG-018: explain_plan"; PO approved).
- [ ] **AC1:** A replan with a previous current run queues `explain_plan` against that run. The job diffs the two stored runs. No changes means no note and no AI call.
- [ ] **AC2:** Gemini's note (low thinking, `explain_plan.v1`) is kept only if `check_summary` passes. Every amount (with its sign) and every date must be in the diff, with no other number in digits, words or other numerals, no markup, not empty, and at most 600 characters.
- [ ] **AC3:** Otherwise, and on an AI outage, a schema failure or without AI, the note is the template built from the diff. Both reject and fallback are tested.
- [ ] **AC4:** The note and its source are stored on plan_run (migration 0004). This week shows it as plain text, escaped.

## Expected paths
- `app/jobs/explain.py`, `app/ai/explain.py`, `app/ai/prompts/explain_plan.v1.md`
- `app/validate/summary.py`
- `app/db/read.py`, `app/db/migrations/0004_plan_summary.sql`, `app/db/schema.sql`
- `app/jobs/replan.py`, `app/worker.py`, `app/planner/diff.py`
- `app/web/repo.py`, `app/web/templates/week.html`
- `tests/test_explain_plan.py`

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from batch 2 plan Q9 (explain_plan has no handler in batch 2)
- 2026-10-03: planned and built in batch 6 (after CHG-008); review fix round 1: signed amounts, numbers in words, the amount a line pays
