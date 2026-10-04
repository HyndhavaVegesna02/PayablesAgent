# Superseded: reports before batch 10

Generated at 2142c95. Batch 10 (PO D28, CHG-034) changed what the scripted owner does: it types every
field the page marks with what the document says, not only a missing due date.

- `workflow-A-2026-10-04.*`: run A's Saturday step says so now, and that step's text changed with it; its
  checks and results did not.
- `2026-10-04-fixtures-baseline/`, `2026-10-04-fixtures-regress-max-steps/`: scenario 03's fields-read check
  now reads the bill as the model read it, due date included, so the owner's typing can't hide a misread.
  Its recorded value changed in report.json; every result is the same.

Kept as they were, for comparison. The current reports are in ../../.
