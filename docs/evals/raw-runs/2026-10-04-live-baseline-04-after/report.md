# Eval report: baseline-04-after

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario | Variant |
|---|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | feba8d0 | 2026-10-04T17:36:16+05:30 | 5 | none |

**Totals:** 5 of 5 runs passed (100% of the runs that finished), 0 errored; 1 of 1 scenarios passed every run; path checks held in 0 of the 0 runs that have them; 5 model calls; 7077 micro-USD.

## Scenarios

| Scenario | Success | Path | Spread (checks met) | Worst run | Model calls | Tool calls | Wasted | Retries | Escalations | Tokens in / out / thoughts | Cost µUSD mean / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Hinglish voice note saying "dedh lakh" | 5/5 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 1.0 | 0.0 | 0.0 | 0.0 | none | 498 / 76 / 202 | 1415 / 1574 |

## What each column means

- **Success:** runs whose every end-to-end check held, of the runs that finished (ERRORED runs are not counted). A live run leaves out the checks that pin the fixture AI's own path.
- **Path:** runs whose trajectory checks held (the path taken: steps, escalations), of the runs of a scenario that has any. A path failure doesn't fail the run's success.
- **Spread:** the least and most share of a scenario's end-to-end checks a run met, across its runs.
- **Worst run:** the run with the fewest checks met, and the component its first failed check (in pipeline order: sort, extract, validate, reconcile, planner, agent) belongs to.
- **Model calls, tool calls, wasted, retries:** means per run, counted from the run's own trace and job table (evals/metrics.py). Wasted = refused tool calls + replies that failed the schema + candidates that failed their checks.
- **Escalations:** the escalation rules any run's trace recorded.
