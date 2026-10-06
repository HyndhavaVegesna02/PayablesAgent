# Superseded: the reports batch 20 regenerated, as they were before it

Generated at their own commits (each report's header names it). Batch 20 (CHG-055) laid docs/evals out by
deliverable and regenerated these, because it changed what they say:

- the two fixture suites (`2026-10-04-fixtures-baseline`, `2026-10-04-fixtures-regress-max-steps`): the totals
  count passes over the runs that finished, with one denominator. No fixture result changed;
- the two live combined pages (`2026-10-04-live-baseline-11x5`, `2026-10-05-live-ablation-v2`) and this tree's
  first ablation table (`2026-10-04-live-ablation-v1`): a Coverage line, plain statuses, the runs each source
  gave, per-harness coverage, and drops only for harnesses scored on more than half the scenarios. Their raw
  runs did not change.

They are kept as they were, for comparison. The current ones are `../../1-eval-report/offline-14x5/`,
`../../3-improvement-and-regression/regression-caught/`, `../../1-eval-report/live-11x5/`,
`../../2-harness-ablation/live/` and `../../raw-runs/2026-10-04-live-ablation-v1/`.
