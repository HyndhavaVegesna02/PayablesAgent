---
id: CHG-041
title: A per-invocation cost cap flag (--max-usd) for the live evals
type: feature
lane: direct
---

## Context
The user authorised live phase 2 on a reduced plan with a cost cap per invocation ($0.50 to $2; about $12 in
all). The budget guard's only cost cap was the hard $5 per invocation.

## Acceptance Criteria
- [ ] AC1: `evals.runner`, `evals.ablation` and `evals.workflow` take `--max-usd D` (dollars, as text: read to
  integer micro-USD, never a float), passed to the invocation's one BudgetGuard.
- [ ] AC2: the flag can only lower the cap: above $5, zero, negative or unreadable is refused before any call.
- [ ] AC3: the guard prints, and the report records (`budget.caps`), the cap in force.

## History
- 2026-10-04: from the user's authorisation of the reduced live phase 2; batch 14 (direct lane)
