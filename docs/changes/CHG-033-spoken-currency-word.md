---
id: CHG-033
title: A currency word, or its start, after a spoken amount is noise (PO D28.1)
type: defect
lane: direct
---

## Context
The live run's scenario 04, run 4 (docs/evals/2026-10-04-live-baseline) gave amount_spoken "dedh lakh rup": "rupaye" cut short. The voice check refused it and the owner had to type the amount.

## Acceptance Criteria
Batch 10 plan, docs/batches/2026-10-04-10/plan.md:
- [ ] AC1: parse_spoken_inr and the voice check's said-words comparison ignore a trailing currency word (rupaye, rupees, rupee, rupiya, rs, rs., inr, ...) or a prefix of one of at least 3 letters ("rup").
- [ ] AC2: anything else at the end is still refused; table tests include garbage trailers.

## History
- 2026-10-04: planned for batch 10 (direct lane)
