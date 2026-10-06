# Harness ablation: ablation-v2-full-11

**How the harnesses are compared (D24).** Every harness gets the same inputs: the seeded worked example and the scenario's emails, uploads and owner actions, in the same order. The bare harness is given them as text (the seeded state written out, each email's text with its attachments, each owner action as a sentence) because it has no ingest pipeline; the model is the same. Where an entry is missing a field the owner must fill, every harness's owner fills it with the same value from the scenario: the full system and the knock-outs type it into the field the page marks, and the bare harness hears it as a sentence, so no harness gets more of the document than another (PO, batch 10). The bare harness's every call, and the no_planner knock-out's plan call, is at medium thinking, the level of the full system's extract and exception work; the full system uses config.yaml's level per job. Live, every harness's calls share one request timeout, 180 seconds, long enough for the bare harness's growing history. Only the harness differs. Every harness is scored on the same `outcome` checks: the business result in its own database (and the week's plan), never how it got there.

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario |
|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | c4cf5f2 | 2026-10-04T22:21:17+05:30 | 2 |

## Outcome checks met, by scenario

| Scenario | full |
|---|---|
| Shortfall week (the worked example) | 2/2 |
| **Outcome success** | 100% |
| Model calls | 6 |
| Cost µUSD | 6169 |

## Which component earned the most

No knock-out compared here lowered outcome success.

| Knock-out | Drop in outcome success (points) |
|---|---|

## What each knock-out patched

Each is a context manager over named seams (evals/knockouts.py), restored after every run; app code has no ablation flag.

- **bare:** evals/bare.py: one growing chat history, every tool (write tools included) on its own database, no checks, no case file, no escalation, no planner, a cap of 20 steps.
