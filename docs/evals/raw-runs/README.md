# Raw runs

You only need these to verify a number. Each folder is a live invocation, under its original dated name
and exactly as it was written; the pages in the numbered folders are generated from them, and
`make check-evidence` re-derives those pages from these files. Each report's header gives its status and,
when it stopped early, the reason as recorded.

## The live suite, 11x5 (for [1-eval-report/live-11x5/](../1-eval-report/live-11x5/report.md))

| Folder | What it is |
|---|---|
| [`2026-10-04-live-baseline/`](2026-10-04-live-baseline/report.md) | First invocation: scenarios 01 to 07; stopped at scenario 08's first run when Google kept refusing calls (a 429 that turned out to be the project's monthly spending cap). |
| [`2026-10-04-live-baseline-part2/`](2026-10-04-live-baseline-part2/report.md) | Second invocation: scenarios 04 and 08 to 11. |
| [`2026-10-04-live-baseline-04-after/`](2026-10-04-live-baseline-04-after/report.md) | Scenario 04 again, once a day number next to a month name was read as a date. |

## The live ablation (for [2-harness-ablation/live/](../2-harness-ablation/live/report.md))

| Folder | What it is |
|---|---|
| `2026-10-04-live-ablation-v2-full/`, `2026-10-04-live-ablation-v2-full-11/` | The full system: every scenario, stopped by its cost cap during scenario 11's second run, then scenario 11 again. Traces kept. |
| `2026-10-04-live-ablation-v2-<harness>/` | The knock-outs and the bare harness, each under its own cost cap. no_rule_checks and no_escalation completed. no_planner stopped on its cost cap after its first scenario; Google's monthly project spending cap (a 429) stopped no_drift_rule after its first scenario, and no_evidence_gate, all_tools, no_case_file and bare before they scored a run. Traces kept. |
| `2026-10-05-live-ablation-v2-<harness>/` | The remaining runs, cheapest first. no_evidence_gate, all_tools and no_planner stopped on their cost caps. The bare harness's last run (scenario 11) stopped on its cap too: that run is ERRORED and unscored, and though this invocation's header says COMPLETE, its budget record says why it stopped, and the table's plain status follows that. Traces kept. |

The table's source table links each of them.

## In this tree only

The first live ablation: `2026-10-04-live-ablation-full/`, `-bare/`, `-bare-after/`, `-no_planner/`,
`-no_rule_checks/`, `-no_escalation/` and `-no_drift_rule/`, an invocation per harness, and
[`2026-10-04-live-ablation-v1/`](2026-10-04-live-ablation-v1/report.md), its table, generated from them. The
second ablation superseded it.
