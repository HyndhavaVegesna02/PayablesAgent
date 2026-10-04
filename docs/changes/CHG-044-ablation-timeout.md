---
id: CHG-044
title: One request timeout for every harness in a live ablation
type: defect
lane: direct
---

## Context
In the live bare-harness ablation, five runs errored on Gemini 504 "Deadline expired": the bare harness's
growing chat history outran config.yaml's 60 s timeout, so those scenarios went unscored.

## Acceptance Criteria (PO)
- [ ] AC1: a live ablation gives every harness the same request timeout (180 s), long enough for the bare
  harness's history; the suite runner and workflows keep config.yaml's.
- [ ] AC2: the ablation report's header says the timeout is the same for every harness.

## History
- 2026-10-04: from the live ablation and the PO; batch 15 (direct lane)
