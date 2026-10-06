# Eval report: pilot-traces

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario | Variant |
|---|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-02.1 | 9c5503258079 | 17000b7 | 2026-10-04T03:28:06+05:30 | 1 | none |

**Totals:** 0 of 2 runs passed (0% of the runs that finished), 0 errored; 0 of 2 scenarios passed every run; path checks held in 1 of the 1 runs that have them; 22 model calls; 122837 micro-USD.

## Scenarios

| Scenario | Success | Path | Spread (checks met) | Worst run | Model calls | Tool calls | Wasted | Retries | Escalations | Tokens in / out / thoughts | Cost µUSD mean / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Hinglish voice note saying "dedh lakh" | 0/1 (0%) | no path checks | 100% – 100% | run 1: crash, 0 failed | 1.0 | 0.0 | 0.0 | 0.0 | none | 475 / 76 / 313 | 1815 / 1815 |
| Missed alert causes drift | 0/1 (0%) | 1/1 | 33% – 33% | run 1: sort, 4 failed | 21.0 | 14.0 | 2.0 | 0.0 | none | 20897 / 2594 / 25497 | 121022 / 121022 |

## Failures (the worst run of each scenario that failed)

**Hinglish voice note saying "dedh lakh"**, run 1: broke at **crash** (FieldErrors: due_date: Enter a date.).

**Missed alert causes drift**, run 1: broke at **sort**.
- `missed-alert-not-polled` (sort): got `1`, wanted `0`
- `written-as-the-pipeline-with-the-case-as-source` (agent): got `pipeline source_docu`, wanted `pipeline agent:case:`
- `drift-case-resolved` (agent): got `ASK_OWNER`, wanted `RESOLVED`
- `gap-closed` (reconcile): got `ASK_OWNER`, wanted `OK`


## What each column means

- **Success:** runs whose every end-to-end check held, of the runs that finished (ERRORED runs are not counted). A live run leaves out the checks that pin the fixture AI's own path.
- **Path:** runs whose trajectory checks held (the path taken: steps, escalations), of the runs of a scenario that has any. A path failure doesn't fail the run's success.
- **Spread:** the least and most share of a scenario's end-to-end checks a run met, across its runs.
- **Worst run:** the run with the fewest checks met, and the component its first failed check (in pipeline order: sort, extract, validate, reconcile, planner, agent) belongs to.
- **Model calls, tool calls, wasted, retries:** means per run, counted from the run's own trace and job table (evals/metrics.py). Wasted = refused tool calls + replies that failed the schema + candidates that failed their checks.
- **Escalations:** the escalation rules any run's trace recorded.
