# Superseded: reports before batch 15

Batch 15 fixed what live phase 2 found.

- `2026-10-04-fixtures-ablation/` (generated at 73b6270): CHG-044 added a sentence to the comparison
  paragraph (one request timeout for every harness, live). Only that paragraph, the commit and the date
  changed; every result is the same.
- `workflow-B-2026-10-04.*` (generated at 2142c95): CHG-043 changed run B's scripted owner to find a debit's
  question by amount and to answer the agent by a stated rule, so two steps' text and checks changed
  (`choice-pressed`; `unmatched-debits-all-explained` keyed by amount). Every result is still PASS.

Kept as they were, for comparison. The current reports are in ../../.
