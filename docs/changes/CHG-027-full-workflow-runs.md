---
id: CHG-027
title: Full-workflow runs
type: feature
lane: planned
---

## Context
A PO interrupt in batch 7 (2026-10-03 22:05, payablesagent-ac for the user). It sits after CHG-010c and before the review, and is planned inline as an addendum to docs/batches/2026-10-03-7/plan.md, with no separate approval round.

## Description
Two scripted fortnights, Mon 12 to Sun 25 Oct 2026. Each runs through the real web routes (owner and helper logged in, every action a form the page rendered, posted with its CSRF token), the real worker and the demo clock, on a freshly reseeded database. Every step has explicit checks, and the report is a step table (PASS/FAIL, actual vs expected) in docs/evals/workflow-<run>-<date>.md with its metadata. `make workflow` runs both. `RUN=A|B` picks one and `N=` sets repeats. `--ai fixtures` runs in `make test`; `--ai live` runs behind the budget guard.

## Acceptance Criteria
The PO's requirements as listed in the plan addendum ("CHG-027", docs/batches/2026-10-03-7/plan.md).

## Expected paths
See .yourteam/backlog.yaml.

## History
- 2026-10-03: added mid-batch by the PO; planned inline; built
