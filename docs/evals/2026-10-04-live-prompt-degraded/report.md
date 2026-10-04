# Eval report: prompt-degraded

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario | Variant |
|---|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-04.2-degraded | 46b35321dff6 | cc6f8bf | 2026-10-04T15:41:07+05:30 | 1 | evals/variants/prompt-degraded.yaml |

Prompt files swapped in by the variant: `extract_bank_alert.v1` ← `evals/variants/prompts/extract_bank_alert.degraded.md`.

**Totals:** 3 of 3 runs passed (100% of the runs that finished), 0 errored; 3 of 3 scenarios passed every run; path checks held in 1 of the 1 runs that have them; 34 model calls; 97467 micro-USD.

## Scenarios

| Scenario | Success | Path | Spread (checks met) | Worst run | Model calls | Tool calls | Wasted | Retries | Escalations | Tokens in / out / thoughts | Cost µUSD mean / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bank debit alert for a planned payment | 1/1 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 4.0 | 0.0 | 0.0 | 0.0 | none | 1237 / 268 / 209 | 2718 / 2718 |
| Missed alert causes drift | 1/1 (100%) | 1/1 | 100% – 100% | all end-to-end checks met | 17.0 | 12.0 | 0.0 | 0.0 | none | 23341 / 2094 / 8751 | 58179 / 58179 |
| Drift with no explanation | 1/1 (100%) | no path checks | 100% – 100% | all end-to-end checks met | 13.0 | 8.0 | 1.0 | 0.0 | none | 16418 / 1651 / 4816 | 36570 / 36570 |

## What each column means

- **Success:** runs whose every end-to-end check held, of the runs that finished (ERRORED runs are not counted). A live run leaves out the checks that pin the fixture AI's own path.
- **Path:** runs whose trajectory checks held (the path taken: steps, escalations), of the runs of a scenario that has any. A path failure doesn't fail the run's success.
- **Spread:** the least and most share of a scenario's end-to-end checks a run met, across its runs.
- **Worst run:** the run with the fewest checks met, and the component its first failed check (in pipeline order: sort, extract, validate, reconcile, planner, agent) belongs to.
- **Model calls, tool calls, wasted, retries:** means per run, counted from the run's own trace and job table (evals/metrics.py). Wasted = refused tool calls + replies that failed the schema + candidates that failed their checks.
- **Escalations:** the escalation rules any run's trace recorded.
