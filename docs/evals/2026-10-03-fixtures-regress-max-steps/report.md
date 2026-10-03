# Eval report: regress-max-steps

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario | Variant |
|---|---|---|---|---|---|---|---|
| fixtures | gemini-3.8-flash | 2026-10-02.1 | 4bf511065aa0 | 696434a | 2026-10-03T19:02:05+05:30 | 5 | evals/variants/regress-max-steps.yaml |

Fixture mode: every model reply is canned (fixtures/ai_replies.json), so runs are deterministic and the tokens and cost are zero. It shows the harness and the code paths, not the model.

**Totals:** 50 of 55 runs passed (91% of the runs that finished), 0 errored; 10 of 11 scenarios passed every run; 285 model calls; 0 micro-USD.

## Scenarios

| Scenario | Success | Spread (checks met) | Worst run | Model calls | Tool calls | Wasted | Retries | Escalations | Tokens in / out / thoughts | Cost µUSD mean / max |
|---|---|---|---|---|---|---|---|---|---|---|
| Bank debit alert for a planned payment | 5/5 (100%) | 100% – 100% | all checks met | 4.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Password-protected statement PDF | 5/5 (100%) | 100% – 100% | all checks met | 4.0 | 0.0 | 0.0 | 0.0 | stake_above_escalation_amount | 0 / 0 / 0 | 0 / 0 |
| Handwritten bill photo | 5/5 (100%) | 100% – 100% | all checks met | 2.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Hinglish voice note saying "dedh lakh" | 5/5 (100%) | 100% – 100% | all checks met | 1.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Same invoice by email and by photo | 5/5 (100%) | 100% – 100% | all checks met | 4.0 | 0.0 | 1.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Payment returned by the bank | 5/5 (100%) | 100% – 100% | all checks met | 7.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Missed alert causes drift | 0/5 (0%) | 86% – 86% | run 1: agent, 1 failed | 11.0 | 6.0 | 1.0 | 0.0 | max_steps | 0 / 0 / 0 | 0 / 0 |
| Drift with no explanation | 5/5 (100%) | 100% – 100% | all checks met | 8.0 | 4.0 | 0.0 | 0.0 | max_steps | 0 / 0 / 0 | 0 / 0 |
| Vendor email changes bank details | 5/5 (100%) | 100% – 100% | all checks met | 4.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |
| Hidden instruction in a vendor email | 5/5 (100%) | 100% – 100% | all checks met | 9.0 | 2.0 | 1.0 | 0.0 | max_steps | 0 / 0 / 0 | 0 / 0 |
| Shortfall week (the worked example) | 5/5 (100%) | 100% – 100% | all checks met | 3.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |

## Failures (the worst run of each scenario that failed)

**Missed alert causes drift**, run 1: broke at **agent**.
- `drift-resolved-in-its-first-run` (agent): got `high max_steps`, wanted `medium none`


## What each column means

- **Success:** runs whose every check held, of the runs that finished (ERRORED runs are not counted).
- **Spread:** the least and most share of a scenario's checks a run met, across its runs.
- **Worst run:** the run with the fewest checks met, and the component its first failed check (in pipeline order: sort, extract, validate, reconcile, planner, agent) belongs to.
- **Model calls, tool calls, wasted, retries:** means per run, counted from the run's own trace and job table (evals/metrics.py). Wasted = refused tool calls + replies that failed the schema + candidates that failed their checks.
- **Escalations:** the escalation rules any run's trace recorded.
