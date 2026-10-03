---
id: CHG-010a
title: Eval system and harness ablation
type: feature
lane: sliced
---

## Context
Split from CHG-010 (Evidence) in the batch 7 plan, docs/batches/2026-10-03-7/plan.md (PO approved, D22-D25). CHG-009 keeps only the Gmail half.

## Description
evals/runner.py, report.py, ablation.py. The 11 TDD scenarios, N=5, scored at three levels (end-to-end, trajectory, component). Fixture and live modes, with a hard budget guard (600 calls, $5) for live. The harness ablation (full vs bare, and the knock-outs). One regression caught (D23); fair bare scoring (D24); the voice fixture (D22).

## Acceptance Criteria
See the batch 7 plan's "CHG-010a" section: its requirements table is the acceptance list, as the PO approved it.

## Expected paths
See .yourteam/backlog.yaml.

## History
- 2026-10-03: split from CHG-010; planned and approved for batch 7
