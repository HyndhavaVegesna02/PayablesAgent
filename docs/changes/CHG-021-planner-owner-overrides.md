---
id: CHG-021
title: Planner honours the owner's authorise_breach and delay_flexible choices
type: feature
lane: planned
---

## Context
Batch 3 plan, Q1. Choosing authorise_breach or delay_flexible is recorded in shortfall_option by CHG-006, but the planner has no input that makes it pay an escalated bill the owner authorised, or use a flexible bill's grace days. TDD: "grace days are used only when the owner chooses the delay option".

## Description
- PO (2026-10-03): MVP scope, batch 4 with CHG-007.
- The owner's choice is recorded through the ledger writer as an evented, owner-actor record (an override row or a payable field, decided at planning), so it has an audit trail like every other owner action.
- build_snapshot reads the overrides that still apply into a new PlanSnapshot field. The planner stays pure: the override is data in the snapshot, never a flag read from anywhere else.
- With an override, an authorised escalated bill gets PAY with an "authorised by the owner below the safety amount" reason, and a delayed flexible bill targets the latest payment day within its grace days.
- To decide at planning: how long a choice lasts (until the bill is paid, or until the next Monday plan) and how it is shown.

## Acceptance Criteria
Batch 4 plan, docs/batches/2026-10-03-4/plan.md (PO approved, D17 and D18).
- [ ] **AC1:** Choosing "Authorise going below the safety amount" makes each escalated bill in that plan PAY on its target day. The reason names the owner's authorisation and the gap, and the option is not offered again while the authorisation covers the breach.
- [ ] **AC1b (D18):** The authorisation records the floor the owner saw. If the replanned lowest balance goes below that floor, it lapses: the bill escalates again with "your authorisation covered a low of ₹X; the plan now goes to ₹Y", the options come back, and the row stays LAPSED with a planner event. An equal or shallower breach stays covered.
- [ ] **AC2:** Choosing a delay_flexible option gives that bill exactly the option's own what-if: grace days used, discount dropped.
- [ ] **AC3:** Overrides are owner-recorded events in plan_override (D17, migration 0002). They end by themselves when their bill is PAID, SPLIT or REOPENED, and the owner can undo one. Every move is evented.
- [ ] **AC4:** The planner stays pure: overrides arrive only through PlanSnapshot. With none, every existing planner test and golden figure is unchanged, and a Hypothesis property checks that stray overrides change nothing.

## Expected paths
- `app/db/migrations/0002_plan_override.sql`
- `app/db/schema.sql`
- `app/db/read.py`
- `app/planner/plan.py`
- `app/planner/options.py`
- `app/ledger/writer.py`
- `app/jobs/replan.py`
- `app/web/actions.py`
- `app/web/repo.py`
- `app/web/routes/attention.py`
- `app/web/templates/attention.html`
- `app/web/templates/week.html`
- `tests/test_planner_overrides.py`
- `tests/test_web_attention.py`
- `tests/test_ledger_write_guard.py`

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-03: drafted from batch 3 plan Q1
- 2026-10-03: PO: MVP scope, batch 4 with CHG-007; override is owner-recorded and evented, planner stays pure
