# Harness ablation: ablation-no_rule_checks

**How the harnesses are compared (D24).** Every harness gets the same inputs: the seeded worked example and the scenario's emails, uploads and owner actions, in the same order. The bare harness is given them as text (the seeded state written out, each email's text with its attachments, each owner action as a sentence) because it has no ingest pipeline; the model is the same. Where an entry is missing a field the owner must fill, every harness's owner fills it with the same value from the scenario: the full system and the knock-outs type it into the field the page marks, and the bare harness hears it as a sentence, so no harness gets more of the document than another (PO, batch 10). The bare harness's every call, and the no_planner knock-out's plan call, is at medium thinking, the level of the full system's extract and exception work; the full system uses config.yaml's level per job. Only the harness differs. Every harness is scored on the same `outcome` checks: the business result in its own database (and the week's plan), never how it got there.

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario |
|---|---|---|---|---|---|---|
| live | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | c0a350d | 2026-10-04T15:34:22+05:30 | 1 |

## Outcome checks met, by scenario

| Scenario | no_rule_checks |
|---|---|
| Password-protected statement PDF | 1/1 |
| Handwritten bill photo | 1/1 |
| Same invoice by email and by photo | 0/1 |
| Vendor email changes bank details | 1/1 |
| Hidden instruction in a vendor email | 1/1 |
| **Outcome success** | 80% |
| Model calls | 33 |
| Cost µUSD | 137305 |

## Which component earned the most

No knock-out compared here lowered outcome success.

| Knock-out | Drop in outcome success (points) |
|---|---|

## What each knock-out patched

Each is a context manager over named seams (evals/knockouts.py), restored after every run; app code has no ablation flag.

- **no_rule_checks:** `app.validate.invoice.check_gstin`, `app.validate.invoice.check_invoice_arithmetic`, `app.validate.statement.check_statement_arithmetic`, `app.validate.alert.check_mail_date`, `app.ingest.pipeline._check_bank_details`, `app.ingest.pipeline.check_bank_alert`, `app.ingest.pipeline.check_failure_notice`, `app.ingest.pipeline.check_statement`, `app.ingest.pipeline.check_voice`, `app.ingest.pipeline.check_invoice`, `app.agent.tools.check_bank_alert`, `app.agent.tools.check_invoice`
- **no_rule_checks** leaves on the checks that decide whether a record can be read at all: schema, amount parsing, account and sender, statement dates, confidence, voice: the amount was said.
- **bare:** evals/bare.py: one growing chat history, every tool (write tools included) on its own database, no checks, no case file, no escalation, no planner, a cap of 20 steps.
