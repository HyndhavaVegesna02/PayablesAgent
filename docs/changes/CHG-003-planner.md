---
id: CHG-003
title: Planner — plan(), options(), diff(), snapshot builder
type: feature
lane:
---

## Context
TDD Part 2, MVP build sequence, Phase 2. Owner: person B. Depends on CHG-002 (domain types).

## Description
`app/planner/forecast.py`, `plan.py`, `options.py`, `diff.py` — a pure function
of `PlanSnapshot` (Part 2, "Planning engine"), implementing the algorithm,
shortfall options and plan diffing exactly as specified. No I/O, no clock, no DB.

## Acceptance Criteria
- [ ] AC1: The worked example (Part 1) golden test reproduces ₹1,83,000 lowest balance, the three shortfall options, ₹3,83,000 after Nandi Foods pays early, and every daily balance in the golden table
- [ ] AC2: Hypothesis checks the Part 1 invariants (safety rule, PAID never disappears, every rupee traces to a ledger record, unresolved drift uses the lower balance) on random snapshots
- [ ] AC3: `plan()` run twice on the same snapshot gives byte-identical output
- [ ] AC4: `diff.py` lists what changed between two plan runs, scoped to amounts and dates that are actually in the list

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 2
