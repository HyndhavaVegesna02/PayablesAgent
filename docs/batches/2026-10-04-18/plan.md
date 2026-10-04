# Batch 18: plan (the live v2 defects, offline)

**Branch:** `batch-18`, cut from main at d090de6. Two direct-lane changes, pre-accepted by the PO on a green
`make test` and `make check-evidence`. No live spend.

- **CHG-053.** The budget guard stops on a permanent billing refusal (402, or a spend-cap 429). A run whose
  model was unavailable (from its trace: a permanent AIUnavailable, or a retryable one on a job's last
  attempt) is ERRORED in the runner, the ablation and the bare harness, never FAILED. Tests: a guard over a
  backend that returns 402 partway through, driven through `run_suite` and `ablation.main`.
- **CHG-054.** Kept traces go to `<keep>/<scenario number>-run<n>/`, through one helper that the runner and
  the bare harness share, and on Windows the copy uses the `\?\` prefix. Test: an ablation that keeps traces
  under an output folder past 260 characters.

The fixture reports are regenerated only if their output changes.

Afterwards, the rest of live ablation v2 runs from main at one commit, after the user's fresh confirmation:
bare all 11 ×1 at $1.10, no_case_file at $0.80, and the six knock-outs at $0.30 each.
