# Eval report: baseline

**ABORTED**: rate limited: a 429 outlasted 5 backoffs. The figures below cover only the runs that finished.

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario | Variant |
|---|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | aba59bd | 2026-10-04T08:13:22+05:30 | 5 | none |

**Totals:** 34 of 36 runs passed (97% of the runs that finished), 1 errored; 6 of 8 scenarios passed every run; path checks held in 5 of the 5 runs that have them; 249 model calls; 805565 micro-USD.

## Scenarios

| Scenario | Success | Path | Spread (checks met) | Worst run | Model calls | Tool calls | Wasted | Retries | Escalations | Tokens in / out / thoughts | Cost µUSD mean / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bank debit alert for a planned payment | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 4.0 | 0.0 | 0.0 | 0.0 | none | 1483 / 276 / 238 | 3044 / 3517 |
| Password-protected statement PDF | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 13.4 | 10.2 | 0.0 | 0.8 | stake_above_escalation_amount | 16569 / 1608 / 14068 | 71216 / 101027 |
| Handwritten bill photo | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 2.0 | 0.0 | 0.0 | 0.0 | none | 2964 / 231 / 452 | 4786 / 5388 |
| Hinglish voice note saying "dedh lakh" | 4/5 (80%) | no path checks | 40% – 100% | run 4: extract, 3 failed | 1.0 | 0.0 | 0.0 | 0.0 | none | 498 / 76 / 229 | 1515 / 2046 |
| Same invoice by email and by photo | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 4.0 | 0.0 | 1.0 | 0.0 | none | 5028 / 713 / 1060 | 10423 / 12243 |
| Payment returned by the bank | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 7.0 | 0.0 | 0.0 | 0.0 | none | 2735 / 522 / 456 | 5722 / 6371 |
| Missed alert causes drift | 5/5 (100%) | 5/5 | 100% – 100% | all end-to-end checks met | 16.8 | 11.8 | 0.0 | 0.0 | none | 22515 / 2058 / 9626 | 60705 / 80636 |
| Drift with no explanation | 0/0 (n/a), 1 errored | no path checks | n/a | n/a | 0.0 | 0.0 | 0.0 | 0.0 | none | 0 / 0 / 0 | 0 / 0 |

## Failures (the worst run of each scenario that failed)

**Hinglish voice note saying "dedh lakh"**, run 4: broke at **extract** (the owner's form refused entry 1: amount: Enter the amount in rupees, like 1,20,000 or Rs.1,20,000.).
- `bill-due-as-the-owner-said` (validate): got `None`, wanted `2026-11-05`
- `amount-is-150000` (extract): got `None`, wanted `15000000`
- `amount-checked-against-the-words` (validate): got `failed: 'dedh lakh rup' is not an amount this app can read from what was said: type it in`, wanted `passed`


## What each column means

- **Success:** runs whose every end-to-end check held, of the runs that finished (ERRORED runs are not counted). A live run leaves out the checks that pin the fixture AI's own path.
- **Path:** runs whose trajectory checks held (the path taken: steps, escalations), of the runs of a scenario that has any. A path failure doesn't fail the run's success.
- **Spread:** the least and most share of a scenario's end-to-end checks a run met, across its runs.
- **Worst run:** the run with the fewest checks met, and the component its first failed check (in pipeline order: sort, extract, validate, reconcile, planner, agent) belongs to.
- **Model calls, tool calls, wasted, retries:** means per run, counted from the run's own trace and job table (evals/metrics.py). Wasted = refused tool calls + replies that failed the schema + candidates that failed their checks.
- **Escalations:** the escalation rules any run's trace recorded.
