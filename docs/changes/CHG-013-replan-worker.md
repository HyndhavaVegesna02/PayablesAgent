---
id: CHG-013
title: Worker and replan — job runner loop, replan/monday_plan jobs, plan persistence
type: feature
lane:
---

## Context
CHG-003's plan flagged this gap: nothing in the backlog owned plan persistence or the planner's state moves. PO approved it on 2026-10-02 for batch 2, alongside CHG-004 and CHG-005. Phase 4's exit (an approved payment plus a debit alert gives PAID) needs persisted plans. Depends on CHG-003.

## Description (PO scope)
- `app/worker.py` job runner loop:
  - claims jobs, dispatches by `job.kind`, retries with backoff and dead-letters failures;
  - writes a heartbeat that `/api/health` reads;
  - replaces the `make worker` stub.
- `replan` job:
  - absorbs queued duplicates;
  - persists `plan_run`, `plan_line`, `plan_day` and `shortfall_option`, setting `is_current` and `inputs_sha256`;
  - applies the planner's CONFIRMED↔PLANNED and REOPENED→PLANNED moves through `transition()` as actor `planner`;
  - writes a PAYABLE_PLANNED event whose after_json/reason carries the projected minimum, the safety amount and the rule-check result, as in Part 1's example event.
- `monday_plan` runs Mon 07:00 Asia/Kolkata via APScheduler and reads time through the Clock.

## Acceptance Criteria
<!-- to be written when planned for batch 2 -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted at PO request during batch 1 planning
- 2026-10-02: from batch 1 review: shortfall options' what-if runs use synthetic payable ids (-payable_id for a split's second part). Persist only real ids; never write what-if plan lines to plan_line (FK to payable).
- 2026-10-02: PO folded in a batch 1 review note. fixtures/seed.py reads DATABASE_PATH from os.environ while the app reads Settings (.env), so `make reseed` could delete a different file than `make run` uses. Make the seed read Settings().database_path. Also handle Windows PermissionError on --fresh when the DB is open.
