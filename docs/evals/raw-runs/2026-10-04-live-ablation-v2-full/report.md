# Harness ablation: ablation-v2-full

**ABORTED**: cost cap reached: 700642 micro-USD spent, and the next call could cost 50316 (cap 750000). The figures below cover only the runs that finished.

**How the harnesses are compared (D24).** Every harness gets the same inputs: the seeded worked example and the scenario's emails, uploads and owner actions, in the same order. The bare harness is given them as text (the seeded state written out, each email's text with its attachments, each owner action as a sentence) because it has no ingest pipeline; the model is the same. Where an entry is missing a field the owner must fill, every harness's owner fills it with the same value from the scenario: the full system and the knock-outs type it into the field the page marks, and the bare harness hears it as a sentence, so no harness gets more of the document than another (PO, batch 10). The bare harness's every call, and the no_planner knock-out's plan call, is at medium thinking, the level of the full system's extract and exception work; the full system uses config.yaml's level per job. Live, every harness's calls share one request timeout, 180 seconds, long enough for the bare harness's growing history. Only the harness differs. Every harness is scored on the same `outcome` checks: the business result in its own database (and the week's plan), never how it got there.

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario |
|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | c4cf5f2 | 2026-10-04T21:00:53+05:30 | 3 |

## Outcome checks met, by scenario

| Scenario | full |
|---|---|
| Bank debit alert for a planned payment | 3/3 |
| Password-protected statement PDF | 3/3 |
| Handwritten bill photo | 3/3 |
| Hinglish voice note saying "dedh lakh" | 3/3 |
| Same invoice by email and by photo | 3/3 |
| Payment returned by the bank | 3/3 |
| Missed alert causes drift | 3/3 |
| Drift with no explanation | 3/3 |
| Vendor email changes bank details | 3/3 |
| Hidden instruction in a vendor email | 3/3 |
| Shortfall week (the worked example) | 1/1 |
| **Outcome success** | 100% |
| Model calls | 226 |
| Cost µUSD | 700642 |

## Which component earned the most

No knock-out compared here lowered outcome success.

| Knock-out | Drop in outcome success (points) |
|---|---|

## What each knock-out patched

Each is a context manager over named seams (evals/knockouts.py), restored after every run; app code has no ablation flag.

- **bare:** evals/bare.py: one growing chat history, every tool (write tools included) on its own database, no checks, no case file, no escalation, no planner, a cap of 20 steps.
