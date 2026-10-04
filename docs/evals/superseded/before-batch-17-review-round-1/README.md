# Superseded: the fixture reports before batch 17's review round 1

Generated at 254454b. They were replaced at the post-fix HEAD because round 1
changed what the reports say:

- in the ablation, the no_case_file row is marked *context only* and left out
  of the comparison: its canned replies are scripted against the case file's
  text, so offline it shows that the context changes, not what that costs;
- scenario 14's outcome is named for what it checks
  (`paper-bill-paid-or-in-review`);
- the path budgets are set from the committed live runs, and the refusal
  budget counts only code's refusals. No fixture result changed with them.

They are kept as they were, for comparison. The current reports are one
folder up. The reports before batch 17 are in `../before-batch-17/`.
