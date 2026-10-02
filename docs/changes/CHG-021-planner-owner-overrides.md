---
id: CHG-021
title: Planner honours the owner's authorise_breach and delay_flexible choices
type: feature
lane:
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
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-03: drafted from batch 3 plan Q1
- 2026-10-03: PO: MVP scope, batch 4 with CHG-007; override is owner-recorded and evented, planner stays pure
