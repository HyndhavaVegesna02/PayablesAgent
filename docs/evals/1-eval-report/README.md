# 1. The eval report

Every TDD scenario, run repeatedly and scored at each level: did it succeed end to end, was the path sound
(the agent's steps, its escalations), and which component broke when it failed (sort, extract, validate,
reconcile, planner or agent).

| Page | What it is | Headline |
|---|---|---|
| [live-11x5/](live-11x5/report.md) | The live suite on Gemini, as one page generated from 3 invocations. | 55 of 55 live runs passed (11 scenarios × 5 runs). 10 of 11 scenarios passed 5/5 in the first invocation that finished their runs; scenario 04 failed (4/5, then 0/5), was fixed, and passed 5/5 on rerun. |
| [offline-14x5/](offline-14x5/report.md) | The same suite and 3 harder fixture-only scenarios, in fixture mode: every model reply is canned, so runs are deterministic and cost nothing. It shows the harness and the code paths, not the model. | 70 of 70 offline runs passed (14 scenarios × 5 runs). |

## Reading the live page

The live suite ran in parts: Google stopped the first invocation partway, the second ran what was left and
scenario 04 again, and the last reran scenario 04 after its fix. The page's first
line, generated like the rest of it, is its Coverage line: the runs scored of those planned, the invocations
and their commits, and every scenario a later invocation ran again, with each earlier result. Its source table
gives each invocation's status in plain words and how many of its runs the page uses; each scenario row's
From column links to the invocation it came from.

Scenario 04 is the one to read about: its results tell a fix, a regression in our own check, and the
fix for that. The story is in
[3-improvement-and-regression/](../3-improvement-and-regression/README.md#scenario-04-a-live-regression-the-suite-caught).

## Built from

- [`2026-10-04-live-baseline`](../raw-runs/2026-10-04-live-baseline/report.md): scenarios 01 to 07, then
  stopped at scenario 08's first run, when Google kept refusing calls (a 429 that turned out to be the
  project's monthly spending cap).
- [`2026-10-04-live-baseline-part2`](../raw-runs/2026-10-04-live-baseline-part2/report.md): scenarios 04 and
  08 to 11.
- [`2026-10-04-live-baseline-04-after`](../raw-runs/2026-10-04-live-baseline-04-after/report.md): scenario 04
  again, once a day number next to a month name was read as a date.

`make check-evidence` re-derives `live-11x5/` from them, and regenerates `offline-14x5/` from the code.
