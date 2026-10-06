# Harness ablation: ablation-v2-no_escalation

**How the harnesses are compared (D24).** Every harness gets the same inputs: the seeded worked example and the scenario's emails, uploads and owner actions, in the same order. The bare harness is given them as text (the seeded state written out, each email's text with its attachments, each owner action as a sentence) because it has no ingest pipeline; the model is the same. Where an entry is missing a field the owner must fill, every harness's owner fills it with the same value from the scenario: the full system and the knock-outs type it into the field the page marks, and the bare harness hears it as a sentence, so no harness gets more of the document than another (PO, batch 10). The bare harness's every call, and the no_planner knock-out's plan call, is at medium thinking, the level of the full system's extract and exception work; the full system uses config.yaml's level per job. Live, every harness's calls share one request timeout, 180 seconds, long enough for the bare harness's growing history. Only the harness differs. Every harness is scored on the same `outcome` checks: the business result in its own database (and the week's plan), never how it got there.

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario |
|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | 154293e | 2026-10-04T23:43:33+05:30 | 1 |

## Outcome checks met, by scenario

| Scenario | no_escalation |
|---|---|
| Bank debit alert for a planned payment | 1/1 |
| Password-protected statement PDF | 1/1 |
| Handwritten bill photo | 1/1 |
| Hinglish voice note saying "dedh lakh" | 1/1 |
| Same invoice by email and by photo | 1/1 |
| Payment returned by the bank | 1/1 |
| Missed alert causes drift | 1/1 |
| Drift with no explanation | 1/1 |
| Vendor email changes bank details | 1/1 |
| Hidden instruction in a vendor email | 1/1 |
| Shortfall week (the worked example) | 1/1 |
| **Outcome success** | 100% |
| Model calls | 79 |
| Cost µUSD | 221386 |

## Which component earned the most

No knock-out compared here lowered outcome success.

| Knock-out | Drop in outcome success (points) |
|---|---|

## What each knock-out patched

Each is a context manager over named seams (evals/knockouts.py), restored after every run; app code has no ablation flag.

- **no_escalation:** `app.agent.escalation.start_thinking`, `app.agent.escalation.run_over`, `app.agent.escalation.after_run`
- **bare:** evals/bare.py: one growing chat history, every tool (write tools included) on its own database, no checks, no case file, no escalation, no planner, a cap of 20 steps.
