# 3. One improvement from evals, and one regression caught

| Page | What it is | Headline |
|---|---|---|
| [live-pilot-before/](live-pilot-before/report.md) | The first live run on Gemini: the BEFORE. | The pilot passed 9 of 11 scenarios; it missed 04 and 07. |
| [live-pilot-after/](live-pilot-after/README.md) | Scenarios 04 and 07 rerun live once the fixes were in, with traces kept: the AFTER. | Both passed: 2 of 2 runs passed. |
| [regression-caught/](regression-caught/report.md) | The suite in fixture mode with the agent's step cap cut from 6 to 2 (`evals/variants/regress-max-steps.yaml`). | Offline, its path check failed in 5 of 5 runs of scenario 07, while 70 of 70 finished runs still passed. |
| [live-prompt-degraded/](live-prompt-degraded/report.md) | A degraded bank-alert prompt (`evals/variants/prompt-degraded.yaml`), live on scenarios 01, 07 and 08, 1 run each. | Not caught: the live model still copied the amounts exactly. |

## The live runs, in order

1. **The pilot passed 9 of 11 scenarios; it missed 04 and 07.** The first live run
   ([live-pilot-before/](live-pilot-before/report.md)) ran the TDD scenarios on Gemini. Scenario 04 (the Hinglish voice note) and scenario 07 (the missed
   alert) failed.
2. **The traces showed where.** The failures were rerun with their traces kept
   ([live-pilot-before/traces/](live-pilot-before/traces/README.md), whose README walks through them).
3. **The root causes were in the harness, not the model.**
   - Scenario 04: the speaker gave a date with no year, so Gemini rightly gave no due date. The rule checks then
     passed the bill with its required date empty and unmarked, and the owner's form refused it.
   - Scenario 07: the agent found the missed alert. It proposed it with field names of its own, and the tool's
     refusal didn't say which fields it wanted. Code then accepted a resolution that relied on nothing.
4. **The fixes.** A missing due date is marked for the owner, and the model is never asked to guess one. The
   prompt and every refusal name the fields; an empty drift resolution is refused; and the case stays the
   source of what the agent found.
5. **The AFTER passed.** [live-pilot-after/](live-pilot-after/README.md) reran scenarios 04 and 07 live: the
   agent resolved the drift case at medium thinking. Its trace showed one more gap, Gmail's `from:` in the
   agent's first search, which the folder mail source now understands. The two traces, the failure and the
   success, are walked through line by line in [docs/traces/](../../traces/README.md).
6. **The 11x5.** The full suite began in
   [`2026-10-04-live-baseline`](../raw-runs/2026-10-04-live-baseline/report.md). A run of scenario 04 heard
   the amount as "dedh lakh rup", "rupaye" cut short; the entry reached the owner with its amount check failed
   and the field empty, which is safe. After it, a cut-short currency word is noise, and the eval's scripted
   owner fills every field the page marks (D28).
7. **The stop was a spending cap, not a rate limit.** Google's 429 was the project's monthly spending cap,
   which waiting can't lift. The budget guard now treats it as permanent and stops the invocation immediately,
   naming the cap, and every invocation runs under its own `--max-usd`. Scenarios 08 to 11, and 04 again, ran
   as [`2026-10-04-live-baseline-part2`](../raw-runs/2026-10-04-live-baseline-part2/report.md), and a
   generated page joins the invocations into
   [one 11x5 table](../1-eval-report/live-11x5/report.md).
8. **Scenario 04 broke again, in our own check.** That is the next section.

## Scenario 04: a live regression the suite caught

Scenario 04's results, in order, as the combined page's Coverage line gives them:
4/5 at aba59bd, 0/5 at 3ad8e01, 5/5 at feba8d0. The first failure was the cut-short currency word above. The second was a regression
we introduced, and the live suite is what caught it.

- **What failed.** In `2026-10-04-live-baseline-part2`, every run of scenario 04 sent the bill to the owner
  with its amount empty, where the AFTER had read it. The amount check said the voice note held an amount the
  app couldn't read in full.
- **Why.** Gemini writes the note as "dedh lakh rupaye 5 November tak dena hai", with no comma after the unit.
  Between the first and second invocations, a stricter reading of the transcript's numbers (commit 728046a: each cluster
  of number words is read whole, or not at all) took the due date's day as more of the amount.
- **Checked offline, commit by commit.** That live transcript, replayed through the amount check of every
  commit from aba59bd to 3ad8e01 that changed it, passes at each one before 728046a and fails at 728046a and
  every one after it, through 3ad8e01. No model call is involved.
- **The fix.** Commit 31d9ffd: a day number next to a month name is a date, never money, with the one
  money-shaped amount rule (D29) unchanged and the live transcript as a table test
  (`tests/test_voice_amount_dates.py`). The rerun,
  [`2026-10-04-live-baseline-04-after`](../raw-runs/2026-10-04-live-baseline-04-after/report.md), at feba8d0,
  reads the amount on every run, and the combined page takes 04's row from it. Workflow A's voice step, rerun
  live, reads it too ([4-end-to-end-workflows/](../4-end-to-end-workflows/README.md)).

The suite caught it, but only because scenario 04 ran live again: in fixture mode the canned transcript has a
comma after the unit, so the offline suite passed throughout. The live transcript is now a test.

## The regression, told straight (D23)

The regression the suite is built to catch offline is the agent's step cap cut from 6 to 2 (`regression-caught/`).
At first it passed every end-to-end check: with the cut cap the drift case still resolves, because the run at
medium runs out and the rerun at high thinking finishes the job. The end result was right and the path was
worse, at a higher thinking level than the work needs. So scenario 07 also checks its path: the drift case
must be resolved in its first run, at medium (`drift-resolved-in-its-first-run`). That check is a
*trajectory* check, reported in its own Path column; it doesn't decide a run's success. Offline,
its path check failed in 5 of 5 runs of scenario 07, while 70 of 70 finished runs still passed.
`tests/test_evals.py` keeps both facts. Every agent scenario also has path budgets: a cap on its agent steps,
set from the live runs, and on calls code refused.

Other checks pin the fixture AI's own scripted path (`fixtures_only`): the agent trying the injected tool
in scenario 10, and the medium-then-high run in scenario 08. A live run leaves them out, since a correct live
model may take another path.

## The degraded prompt

`evals/variants/prompt-degraded.yaml` swaps a "simplified" bank-alert prompt in for a suite. Canned replies
ignore prompts, so only a live run can say whether the suite catches it. It ran
live on scenarios 01, 07 and 08, 1 run each ([live-prompt-degraded/](live-prompt-degraded/report.md)), and didn't catch the regression: the
live model still copied the amounts exactly. That's a result, reported as it is; repeated runs per
scenario are what would say how often it slips.

## Built from

- `live-pilot-before/`, `live-pilot-after/` and `live-prompt-degraded/` are live invocations, kept here under
  shorter names; `regression-caught/` is regenerated from the code by `make check-evidence`.
- The scenario 04 story uses the 11x5's invocations in [raw-runs/](../raw-runs/README.md).
