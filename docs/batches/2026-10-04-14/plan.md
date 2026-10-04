# Batch 14: plan (a cost cap per live invocation)

**Branch:** `batch-14`, cut from main at 339c481. One direct-lane change, CHG-041: `--max-usd` on the three
eval CLIs, read to integer micro-USD and passed to the one BudgetGuard; it can only lower the hard $5 cap.
Offline; the user's reduced live phase 2 runs on it after the gate.
