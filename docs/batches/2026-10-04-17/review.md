# Batch 17 review

One review round (PO: one per change), by a yt-reviewer over `fa88b80..bd73700`, all seven changes.
Verdict: FIX_REQUIRED, three blocking findings. The fixes are in `ea91d7a`. The evidence was regenerated at
`0bb184d`, and the old copies are under `docs/evals/superseded/before-batch-17-review-round-1/`.

## Blocking, fixed

1. **`make test` failed on the regenerated reports.** `tests/test_evals.py` still expected 11 scenarios and
   the old path totals. It now expects 14 scenarios (11 TDD and 3 harder) and path checks on 02, 07, 08,
   10, 13 and 14. (CHG-051, CHG-050)
2. **CHG-049 AC2 is not met for no_case_file, and the gap was disclosed only in a commit message.**
   - The canned replies are scripted against the case file's text, so what they answer to a chat says
     nothing about what a model would. A scripted outcome difference would be the script's, not the model's.
   - Offline, the fixture ablation marks the row *context only* and leaves it out of the comparison and of
     the consolidated table.
   - The limit is now recorded in CHG-049.md, the knock-outs docstring, the ablation's fixture note and
     the evals README.
   - **The proposed AC amendment is for the PO to decide.**
3. **The path budgets failed known-good live runs.**
   - On 02, every committed live run that passed would have failed the budget; on 07, one of them would.
   - Each budget is now set from the committed live runs' agent steps, with a margin. Each comment cites
     its source. A new test holds every live budget at or above the most that any passing committed live
     run used.
   - 13 and 14 are fixture-only, so their budgets will be set again after their first live run. (CHG-050)

## Should-fix, fixed

4. **The refusal budget counted the word "refused" anywhere,** including the model's own notes and
   summary. It now counts only what code writes: its refusal notes and a tool's refused result. All six
   scenarios share one definition, and a test covers both cases.
5. **`keep` had two meanings,** so the bare harness's traces sat one level shallower than the others. Every
   harness now keeps its traces at `traces/<harness>/<scenario>-run<n>/`, and the test checks this
   layout. (CHG-047)
6. **README "How to lift it" overstated what lifts.** It now names the three files that lift as they are
   and the parts written against this app. (CHG-052)

## Nits, fixed

- The threat model:
  - "(below)" now reads "section 3 above";
  - the live run count is left to the report;
  - the minimisation bullet says where a vendor's full extracted bank details are kept (the candidate
    record and the trace).
- The no_escalation note cites the 11x5 page's path check.
- D25's link now points to CHG-010c.
- Scenario 14's outcome is renamed `paper-bill-paid-or-in-review`, and its `passes_when` says the bill
  goes to review.
- The README evidence table and the demo script said "four knock-outs". They now say seven.

## Left as is

- `no_evidence_gate` re-implements the write half of `apply_final`. That is acceptable under the AC's seam
  name (the reviewer's view too). It will need a look if `apply_final` changes.
- `docs/notes/agent-permissions.md` is stale. It went stale in batch 8, when `app/agent/tools.py` changed,
  not in this batch, so it stays quarantined.

## Gates

Every change's gate is recorded in batch.yaml by `yt_gate.py --record`. The runs from before the fix are
kept: `make test` exited 2 on the stale path-total test. Every change's last run, after the fix, passes:
`make test` exits 0 and `make check-evidence` exits 0. The prepatch passed for every change.
CHG-046 and CHG-052 changed no test files; the evidence-doc and citation tests guard them. No live spend.

## PO verdict

ACCEPT for CHG-046 to CHG-052, as a whole (payablesagent-ac, 2026-10-04). The PO checked 43ab9de independently: the full suite and the import contracts pass. Decision D31 amends CHG-049 AC2 for no_case_file: "proved in fixture mode to change the model's context; its outcome effect measured live". If the live run shows no outcome drop for it, that is reported as found.
