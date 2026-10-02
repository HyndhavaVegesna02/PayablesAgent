---
id: CHG-013
title: Worker and replan — job runner loop, replan/monday_plan jobs, plan persistence
type: feature
lane: planned
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
Batch 2 plan, docs/batches/2026-10-02-2/plan.md (these replace the drafted ones).

- [ ] AC1: The worker claims one queued job, dispatches it by `kind`, and marks it done. A failing handler is retried with exponential backoff and dead-lettered after `max_attempts`. A `PermanentJobError` dead-letters at once. A kind with no handler stays queued.
- [ ] AC2: A replan persists `plan_run` (with `inputs_sha256`, `planner_version` and `is_current`), plus `plan_line`, `plan_day` and `shortfall_option`. Exactly one run per business is current.
- [ ] AC3: A replan on the seeded worked example persists:
  - the 14 golden balances;
  - lines with 4 PAY and 1 ESCALATE;
  - 3 options.

  It moves the 4 PAY bills to PLANNED and leaves Prime Chem CONFIRMED. Each move goes through the writer as `planner`, with the Part 1-style reason.
- [ ] AC4: A second replan whose decision for a PLANNED bill turns to WAIT or ESCALATE moves it back to CONFIRMED, and a changed pay date updates `planned_date` with an event.
- [ ] AC5: Two replan requests made while one is still queued result in one job.
- [ ] AC6: `monday_plan` is scheduled for Mon 07:00 Asia/Kolkata. With the FakeClock, the next fire time is computed correctly, and the job runs a replan with `triggered_by='monday'`.
- [ ] AC7: `/api/health` reports the worker's last heartbeat. `make worker` runs the loop instead of failing.
- [ ] AC8: The seed reads `DATABASE_PATH` through `Settings`. `--fresh` on a locked DB file exits with a clear message instead of a traceback (PO fold-in).

## Expected paths
- `app/worker.py`
- `app/jobs/replan.py`
- `app/jobs/queue.py`
- `app/ledger/writer.py`
- `app/planner/plan.py`
- `app/main.py`
- `fixtures/seed.py`
- `Makefile`
- `CLAUDE.md`
- `tests/test_worker.py`
- `tests/test_replan.py`
- `tests/test_scheduler.py`
- `tests/test_health.py`
- `tests/test_seed.py`
- `tests/test_jobs_queue.py`

## Open Questions
None. PO accepted every default on 2026-10-02 (see the plan's PO decisions).

## History
- 2026-10-02: drafted at PO request during batch 1 planning
- 2026-10-02: from batch 1 review: shortfall options' what-if runs use synthetic payable ids (-payable_id for a split's second part). Persist only real ids; never write what-if plan lines to plan_line (FK to payable).
- 2026-10-02: PO folded in a batch 1 review note. fixtures/seed.py reads DATABASE_PATH from os.environ while the app reads Settings (.env), so `make reseed` could delete a different file than `make run` uses. Make the seed read Settings().database_path. Also handle Windows PermissionError on --fresh when the DB is open.
- 2026-10-02: planned for batch 2 (lane planned: consumes APScheduler CronTrigger and CHG-003's PlanResult). ACs and design in docs/batches/2026-10-02-2/plan.md; Q1, Q5, Q6, Q9, Q10 there.
- 2026-10-02: PO approved the batch 2 plan; status ready, batch 2.
- 2026-10-03: as built, after review rounds 1-2: the worker requeues a job left running (counting the attempt) at start and after a busy-database error; the loop survives a refused heartbeat; the rule check's projected minimum counts only the bills the plan pays (wording says so); the Monday plan has a 6h misfire grace.
