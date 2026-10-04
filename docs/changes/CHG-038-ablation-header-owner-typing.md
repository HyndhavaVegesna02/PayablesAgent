---
id: CHG-038
title: The ablation report's header says the bare harness hears the same owner-typed values
type: docs
lane: direct
---

## Context
Batch 10 (CHG-034) gave the scripted owner the document's values to type into every field the page marks.
The bare harness is told the same values as sentences. The PO accepted this as fair (batch 10 verdict, note
2) and asked that the ablation report's header say so.

## Acceptance Criteria
- [ ] AC1: the ablation report's comparison paragraph says every harness's owner types the same values from
  the scenario (the bare harness hears them as sentences), so no harness gets more of the document than another.
- [ ] AC2: the committed fixture ablation report is regenerated at the change's commit, the old one kept as
  superseded; `make check-evidence` passes.

## History
- 2026-10-04: from the PO's batch 10 verdict; planned for batch 11 (direct lane)
