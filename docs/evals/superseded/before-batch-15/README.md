# Superseded: reports before batch 15

Batch 15 fixed what live phase 2 found.

- `2026-10-04-fixtures-ablation/` (generated at 73b6270): CHG-044 added a sentence to the comparison
  paragraph (one request timeout for every harness, live). Only that paragraph, the commit and the date
  changed; every result is the same.
- `workflow-B-2026-10-04.*` (generated at 2142c95): CHG-043 changed run B's scripted owner to find a debit's
  question by amount and to answer the agent by a stated rule, so two steps' text and checks changed
  (`choice-pressed`; `unmatched-debits-all-explained` keyed by amount). Every result is still PASS.

- `workflow-A-2026-10-04-live.*`, `workflow-B-2026-10-04-live.*` (live, at 035ba69 and 79c838d): the
  first live runs of the two fortnights, before CHG-042 (A's voice step) and CHG-043 (B's scripted owner).
  They are the BEFORE for the live reruns now in ../../.

- `2026-10-04-live-baseline-11x5/`: the combined page before scenario 04's AFTER; its 04 row came from
  `live-baseline-part2`. The current page is combined from three invocations, 04's row from the AFTER.

Kept as they were, for comparison. The current reports are in ../../.
