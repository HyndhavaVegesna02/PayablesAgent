# 2. The harness ablation

`make ablation` runs the same scenarios under the full system, a bare harness (one growing chat history,
every tool including the write tools, no checks, no case file, no escalation, no planner) and
7 knock-outs, each removing one control at a named seam (`evals/knockouts.py`). The model is the same; only the
harness differs. Every harness is scored on the same `outcome` checks: the business result alone.

| Page | What it is | Headline |
|---|---|---|
| [live/](live/report.md) | The live ablation on Gemini, as one table generated from 16 invocations. | The harness: 80 points of outcome success, paired on the 10 scenarios both scored (full 100%, bare 20%). no_drift_rule and no_rule_checks cost the most: 9 points each, which at one run per scenario is 1 scenario each. all_tools and no_planner: not measured live (1/11 scenarios). |
| [offline/](offline/report.md) | The ablation in fixture mode, every harness on every scenario. It shows the code paths, not the model. | |

## Reading the live table

- **The headline is the harness itself:** the full system against the bare harness, on the scenarios both
  were scored on. A knock-out's drop is paired the same way: the full system's success on the scenarios that
  knock-out was scored on, less the knock-out's own.
- **Coverage first:** the full system ran 3 runs per scenario (2 on 11-shortfall-week), and
  the bare harness and the knock-outs ran 1 run per scenario, each under its own cost cap.
  The Coverage table gives each harness's scenarios scored and runs per cell. A drop is shown only for a
  harness scored on more than half the scenarios: one that stopped after a few scenarios is *not measured
  live*, and can't be the component that earned the most.
- **A knock-out's drop rests on single runs.** At its runs per scenario, a scenario it lost is a single run
  that failed. The
  offline ablation runs every scenario, but on canned replies, so it shows that a control is wired in, not
  what the model does without it.
- **Stopped invocations.** Some invocations stopped on their own cost cap, and some on Google's monthly
  project spending cap. Their finished runs are valid; the source table says which stopped and why, and how
  many of each one's runs the table uses.

## What the live table shows

- The knock-outs that lowered outcome success:
  - no_rule_checks lost scenario 05, the same invoice by email and by photo: without the duplicate check both
    copies waited for the owner, and the bill never became the one payable the outcome asks for;
  - no_drift_rule lost scenario 08, the drift nothing explains: planning from the calculated balance rather
    than the lower one, the plan counted money that wasn't there.
- no_case_file and no_escalation, scored on every scenario, lost nothing, at the runs per scenario the
  Coverage table gives.
- no_evidence_gate stopped on its cost cap partway; its drop covers the scenarios it scored, which the
  Coverage table names.
- all_tools and no_planner were each stopped by their cost cap before they scored a second scenario, so the
  table shows no drop for them.

## Why some knock-outs showed no effect, and what would show one

These are results, not gaps to hide.
- **no_escalation** (no stake rule, no rerun at high, a plain step cap). On 07 the agent found the missing
  alert at medium thinking in its first run (the path check `drift-resolved-in-its-first-run` on
  [the live suite](../1-eval-report/live-11x5/report.md)), so neither the stake rule nor the rerun was needed;
  on 08 nothing explains the gap, so every path ends with the owner. Escalation earns its place when the
  medium run fails and a high one would succeed. The scenario to add is a missed alert that takes more
  searching than the medium step cap allows, run with repeated runs per scenario.
- **no_case_file** (a growing chat history in place of the case file). A likely reason: within one job a
  chat holds what the case file holds. The case file should earn its place across jobs (a retry, or a resume
  after the owner answers), where a chat starts again and the case file doesn't.
- **no_planner** (the plan comes from the model, given the planner's snapshot as text). The planner earns its
  place when the arithmetic is long: many bills, more than one payment day, a floor that only a split keeps. Workflow
  A's fortnight is that case, and it is where a no_planner run should be scored next.

## Fixture mode, and what it does not show

In fixture mode every model reply is canned. The bare harness and the no_planner knock-out need replies that
no fixture has: they run on a stand-in that plans nothing, are marked *mechanics only*, and are left out of the
comparison. `no_case_file` is marked *context only* and left out too: the canned replies are scripted against
the case file's text, so what they answer to a chat says nothing about what a model would.

## Built from

The live invocations in [raw-runs/](../raw-runs/README.md), named `2026-10-04-live-ablation-v2-*` and
`2026-10-05-live-ablation-v2-*`; the table's source table links each one. `make check-evidence` re-derives
`live/` from them and regenerates `offline/` from the code.
