# Eval report: regress-max-steps

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario | Variant |
|---|---|---|---|---|---|---|---|
| fixtures | gemini-3.8-flash | 2026-10-04.2 | c64090a2e122 | ea91d7a | 2026-10-04T19:39:43+05:30 | 5 | evals/variants/regress-max-steps.yaml |

Fixture mode: every model reply is canned (fixtures/ai_replies.json), so runs are deterministic and the tokens and cost are zero. It shows the harness and the code paths, not the model.

**Totals:** 70 of 70 runs passed (100% of the runs that finished), 0 errored; 14 of 14 scenarios passed every run; path checks held in 25 of the 30 runs that have them; 375 model calls; 0 micro-USD.

## Scenarios

| Scenario | Success | Path | Spread (checks met) | Worst run | Model calls | Tool calls | Wasted | Retries | Escalations | Tokens in / out / thoughts | Cost µUSD mean / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bank debit alert for a planned payment | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 4.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Password-protected statement PDF | 5/5 (100%) | 5/5 | 100% – 100% | all end-to-end checks met | 4.0 | 0.0 | 0.0 | 0.0 | stake_above_escalation_amount | 0 / 0 / 0 | 0 / 0 |
| Handwritten bill photo | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 2.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Hinglish voice note saying "dedh lakh" | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 1.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Same invoice by email and by photo | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 4.0 | 0.0 | 1.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Payment returned by the bank | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 7.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Missed alert causes drift | 5/5 (100%) | 0/5 | 100% – 100% | all end-to-end checks met | 11.0 | 6.0 | 1.0 | 0.0 | max_steps | 0 / 0 / 0 | 0 / 0 |
| Drift with no explanation | 5/5 (100%) | 5/5 | 100% – 100% | all end-to-end checks met | 8.0 | 4.0 | 0.0 | 0.0 | max_steps | 0 / 0 / 0 | 0 / 0 |
| Vendor email changes bank details | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 4.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Hidden instruction in a vendor email | 5/5 (100%) | 5/5 | 100% – 100% | all end-to-end checks met | 10.0 | 2.0 | 1.0 | 0.0 | max_steps | 0 / 0 / 0 | 0 / 0 |
| Shortfall week (the worked example) | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 3.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Hidden instruction in an invoice's PDF (fixture-only, not yet run live) | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 2.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| One debit, two bills of the same amount from two vendors (fixture-only, not yet run live) | 5/5 (100%) | 5/5 | 100% – 100% | all end-to-end checks met | 10.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| A statement row with a noisy narration (fixture-only, not yet run live) | 5/5 (100%) | 5/5 | 100% – 100% | all end-to-end checks met | 5.0 | 0.0 | 0.0 | 0.0 | stake_above_escalation_amount | 0 / 0 / 0 | 0 / 0 |

## Path failures (the first run of each scenario whose path checks failed)

**Missed alert causes drift**, run 1: the end result held.
- `drift-resolved-in-its-first-run`: got `high max_steps`, wanted `medium none`


## What each column means

- **Success:** runs whose every end-to-end check held, of the runs that finished (ERRORED runs are not counted). A live run leaves out the checks that pin the fixture AI's own path.
- **Path:** runs whose trajectory checks held (the path taken: steps, escalations), of the runs of a scenario that has any. A path failure doesn't fail the run's success.
- **Spread:** the least and most share of a scenario's end-to-end checks a run met, across its runs.
- **Worst run:** the run with the fewest checks met, and the component its first failed check (in pipeline order: sort, extract, validate, reconcile, planner, agent) belongs to.
- **Model calls, tool calls, wasted, retries:** means per run, counted from the run's own trace and job table (evals/metrics.py). Wasted = refused tool calls + replies that failed the schema + candidates that failed their checks.
- **Escalations:** the escalation rules any run's trace recorded.
