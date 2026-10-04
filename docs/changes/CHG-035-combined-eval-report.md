---
id: CHG-035
title: One 11x5 page combined from the two live invocations, generated, never typed
type: feature
lane: direct
---

## Context
Phase 2's 11x5 live run stopped on a 429 after scenarios 01-07; 08-11 (and 04 again, after D28) run later as baseline-part2.

## Acceptance Criteria
Batch 10 plan, docs/batches/2026-10-04-10/plan.md:
- [ ] AC1: `python -m evals.report combine` builds a combined md and json from two or more report.json files: for each scenario the latest part that ran it wins, each row names its source, and the header lists every source's commit, date, status and spend.
- [ ] AC2: make check-evidence also re-derives every committed combined report from its sources (offline).

## History
- 2026-10-04: planned for batch 10 (direct lane)
