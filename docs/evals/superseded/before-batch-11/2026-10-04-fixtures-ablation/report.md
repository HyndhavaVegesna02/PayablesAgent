# Harness ablation: ablation

**How the harnesses are compared (D24).** Every harness gets the same inputs: the seeded worked example and the scenario's emails, uploads and owner actions, in the same order. The bare harness is given them as text (the seeded state written out, each email's text with its attachments, each owner action as a sentence) because it has no ingest pipeline; the model is the same. The bare harness's every call, and the no_planner knock-out's plan call, is at medium thinking, the level of the full system's extract and exception work; the full system uses config.yaml's level per job. Only the harness differs. Every harness is scored on the same `outcome` checks: the business result in its own database (and the week's plan), never how it got there.

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario |
|---|---|---|---|---|---|---|
| fixtures | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | 7ad9d92 | 2026-10-04T04:58:38+05:30 | 1 |

Fixture mode: every model reply is canned, so the full system and the knock-outs that keep its prompts are deterministic, and tokens and cost are zero. The rows marked *mechanics only* ran on a stand-in that plans nothing; they show the harness runs, not what it scores, and are left out of the comparison. The live run (`--ai live --yes-spend`) scores them.

## Outcome checks met, by scenario

| Scenario | full | bare | no_planner | no_rule_checks | no_escalation | no_drift_rule |
|---|---|---|---|---|---|---|
| Bank debit alert for a planned payment | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Password-protected statement PDF | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Handwritten bill photo | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Hinglish voice note saying "dedh lakh" | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Same invoice by email and by photo | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 0/1 | 1/1 | 1/1 |
| Payment returned by the bank | 1/1 | 1/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Missed alert causes drift | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Drift with no explanation | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 0/1 |
| Vendor email changes bank details | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Hidden instruction in a vendor email | 1/1 | 1/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| Shortfall week (the worked example) | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 1/1 |
| **Outcome success** | 100% | 18% *mechanics only* | 73% *mechanics only* | 91% | 100% | 91% |
| Model calls | 70 | 22 | 76 | 70 | 89 | 69 |
| Cost µUSD | 0 | 0 | 0 | 0 | 0 | 0 |

## Which component earned the most

Knocking out **no_drift_rule, no_rule_checks** cost the most: outcome success fell by 9 points from the full system's 100%.

| Knock-out | Drop in outcome success (points) |
|---|---|
| no_rule_checks | 9 |
| no_drift_rule | 9 |
| no_escalation | 0 |

## What each knock-out patched

Each is a context manager over named seams (evals/knockouts.py), restored after every run; app code has no ablation flag.

- **no_planner:** `app.jobs.replan.plan`
- **no_rule_checks:** `app.validate.invoice.check_gstin`, `app.validate.invoice.check_invoice_arithmetic`, `app.validate.statement.check_statement_arithmetic`, `app.validate.alert.check_mail_date`, `app.ingest.pipeline._check_bank_details`, `app.ingest.pipeline.check_bank_alert`, `app.ingest.pipeline.check_failure_notice`, `app.ingest.pipeline.check_statement`, `app.ingest.pipeline.check_voice`, `app.ingest.pipeline.check_invoice`, `app.agent.tools.check_bank_alert`, `app.agent.tools.check_invoice`
- **no_escalation:** `app.agent.escalation.start_thinking`, `app.agent.escalation.run_over`, `app.agent.escalation.after_run`
- **no_drift_rule:** `app.jobs.replan.build_snapshot`
- **no_rule_checks** leaves on the checks that decide whether a record can be read at all: schema, amount parsing, account and sender, statement dates, confidence, voice: the amount was said.
- **bare:** evals/bare.py: one growing chat history, every tool (write tools included) on its own database, no checks, no case file, no escalation, no planner, a cap of 20 steps.
