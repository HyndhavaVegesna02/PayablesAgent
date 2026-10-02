---
id: CHG-003
title: Planner — plan(), options(), diff(), snapshot builder
type: feature
lane: planned
---

## Context
TDD Part 2, MVP build sequence, Phase 2. Owner: person B. Depends on CHG-002 (writer, seed, money formatter).

Plan: docs/batches/2026-10-02-1/plan.md.

Lane `planned`. Trigger: this change consumes a contract it didn't write, namely the snapshot produced by CHG-002's schema and writer. That makes the contract grid mandatory.

## Description
`app/planner/plan.py`, `forecast.py`, `options.py` and `diff.py` make up a pure function of `PlanSnapshot` (Part 2, "Planning engine"). They implement the algorithm, the shortfall options and plan diffing as specified, with no I/O, no clock and no DB access.

The snapshot builder is `app/db/read.py::build_snapshot()`.

Out of scope: persisting plan runs and applying the planner's transitions. The proposed CHG-013 covers both.

## PO decisions (2026-10-02, payablesagent-ac)
- D1: PlanSnapshot.commitments has no schema table. The builder passes an empty tuple. The type and the planner support stay, for what-ifs. No table is added.
- D6: the early_receipt date is the last weekday (Mon–Fri) strictly before the last payment day strictly before the breach day. In the worked example, breach Thu 22 → Mon 19 → Fri 16 Oct.

## Acceptance Criteria
- [ ] AC1: The worked-example golden test (Part 1) reproduces:
  - the ₹1,83,000 lowest balance;
  - the three shortfall options;
  - ₹3,83,000 after Nandi Foods pays early;
  - every daily balance in the golden table.
- [ ] AC2: Hypothesis checks these invariants on random snapshots:
  - the safety rule holds;
  - every rupee traces to a snapshot record;
  - unresolved drift uses the lower balance;
  - statutory bills never escalate;
  - each plannable bill gets exactly one line;
  - every amount is an int.

  ("PAID never disappears" moved to CHG-002 AC5, per D5.)
- [ ] AC3: Running `plan()` twice on the same snapshot gives byte-identical output, including across processes with different PYTHONHASHSEED values.
- [ ] AC4: `diff.py` lists what changed between two plan runs. It also exposes the exact set of amounts and dates it mentions, which is the allow-list for explain_plan's check.
- [ ] AC5: The golden test locks the D6 early_receipt rule (Fri 16 Oct for Nandi). The option is not offered when the computed date falls before today.
- [ ] AC6: Every snapshot input row in the plan's contract grid has its empty, absent and failure behaviour driven by a test against a real migrated DB.
- [ ] AC7: Seed → build_snapshot(today=2026-10-12) → plan() produces the same canonical bytes as the hand-built golden snapshot.
- [ ] AC8: ESCALATE reasons include the breach day and the gap. Bills due after the horizon get WAIT. Overdue bills target the next payment day on or after today.
- [ ] AC9 (D9): All three discount branches have tests:
  - discount taken;
  - discount skipped, so the bill pays on its due date;
  - discount skipped and the due date also breaches, so the bill gets ESCALATE.

  The fallback reason names the skipped discount.

## Expected paths
- app/planner/plan.py
- app/planner/forecast.py
- app/planner/options.py
- app/planner/diff.py
- app/db/read.py
- tests/test_planner_forecast.py
- tests/test_planner_targets.py
- tests/test_planner_golden.py
- tests/test_planner_options.py
- tests/test_planner_properties.py
- tests/test_planner_determinism.py
- tests/test_planner_diff.py
- tests/test_snapshot_builder.py

## Open Questions
None. PO answered both on 2026-10-02:
- **D8 (Q3):** `PlanSnapshot.uncounted_inflows` is added as a PO-approved extension of the TDD type.
- **D9 (Q4 override):**
  - `discount_paise` is the paise saved when the bill is paid by `discount_by`.
  - If paying on the discount target would breach the safety amount, the bill falls back to its due-date target at the full amount. It is escalated only if that also breaches.
  - The fallback reason says the discount was skipped because taking it would breach.
  - Each branch gets one unit test.

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 2
- 2026-10-02: refined for batch 1 with PO decisions D1 and D6; AC2 revised; AC5–AC8 added
- 2026-10-02: batch 1 fix round 1 (review FIX_REQUIRED). build_snapshot now reads inside one read transaction. WAIT is decided on the computed target, as approved plan step 4(d) says: a bill due after the horizon still gets a PAY line if its latest payment day before the due date, or a safe discount day, is inside the horizon. This narrows AC8's literal wording; flagged to the PO at verdict. ask_ca keeps PAYMENT_EXPECTED bills in its statutory-only rerun, because they are approved commitments. bank_account.status (no defined values) is not read.
