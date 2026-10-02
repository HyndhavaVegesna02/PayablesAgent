---
id: CHG-021
title: Planner honours the owner's authorise_breach and delay_flexible choices
type: feature
lane:
---

## Context
Batch 3 plan, Q1. Choosing authorise_breach or delay_flexible is recorded in shortfall_option by CHG-006, but the planner has no input that makes it pay an escalated bill the owner authorised, or use a flexible bill's grace days. TDD: "grace days are used only when the owner chooses the delay option".

## Description
- A snapshot input (from chosen options that still apply) that the pure planner reads: authorised escalated bills are paid with an "authorised by the owner below the safety amount" reason, and delayed flexible bills target the latest payment day within their grace days.
- Decide how long a choice lasts (until the bill is paid, or until the next Monday plan) and how it is shown.

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-03: drafted from batch 3 plan Q1
