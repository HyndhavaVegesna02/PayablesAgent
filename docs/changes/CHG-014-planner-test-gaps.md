---
id: CHG-014
title: Planner test gaps from batch 1 review
type: chore
lane:
---

## Context
Non-blocking notes from the batch 1 planner review:
- The split option's rest part copies grace_days (options.py), but no test drives it; mutant M34 survives. The what-if snapshot isn't exposed on OptionResult, so a test needs either that exposure or a scenario that reruns a split.
- build_snapshot with the caller already in a transaction (the in_transaction=True path) is untested.
- The contract-grid cell "sqlite error propagates" is untested.
- test_planner_determinism's PYTHONHASHSEED check guards str hashing only; int-set ordering is not covered by it.

## Description
<!-- to be written when planned -->

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: logged from batch 1 review notes (PO: non-blocking notes become backlog chores)
