---
id: CHG-032
title: A check that the committed fixture-mode reports reproduce
type: chore
lane: direct
---

## Context
Found in batch 8's review (round 2, evals M4). A fix changed one message that the eval runner emits, and
the committed ablation report.json kept the old text. Only a manual regenerate-and-diff caught it, and the
first manual check compared the .md files only.

## Description
A check, like `scripts/make_traces.py`'s, that regenerates every fixture-mode report (the 11x5 baseline,
the step-cap regression, the ablation, and workflow A and B) and compares each md and json file with the
committed one, setting aside only the commit and date fields. Running it inside `make test` costs the
whole suite plus the ablation (about a minute on fixtures), so the PO decides where it runs: make test, a
separate make target, or the batch-close gate only.

## Acceptance Criteria
<!-- to be written when planned -->

## History
- 2026-10-04: drafted from batch 8's review
- 2026-10-04: PO: its own make target, `make check-evidence`, kept out of make test, and a required step in the batch-close gate; direct lane, first in the next work
