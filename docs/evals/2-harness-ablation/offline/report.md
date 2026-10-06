# Harness ablation: ablation

**How the harnesses are compared (D24).** Every harness gets the same inputs: the seeded worked example and the scenario's emails, uploads and owner actions, in the same order. The bare harness is given them as text (the seeded state written out, each email's text with its attachments, each owner action as a sentence) because it has no ingest pipeline; the model is the same. Where an entry is missing a field the owner must fill, every harness's owner fills it with the same value from the scenario: the full system and the knock-outs type it into the field the page marks, and the bare harness hears it as a sentence, so no harness gets more of the document than another (PO, batch 10). The bare harness's every call, and the no_planner knock-out's plan call, is at medium thinking, the level of the full system's extract and exception work; the full system uses config.yaml's level per job. Live, every harness's calls share one request timeout, 180 seconds, long enough for the bare harness's growing history. Only the harness differs. Every harness is scored on the same `outcome` checks: the business result in its own database (and the week's plan), never how it got there.

| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario |
|---|---|---|---|---|---|---|
| fixtures | gemini-3.8-flash | 2026-10-04.2 | 51f54558b581 | ea91d7a | 2026-10-04T19:39:56+05:30 | 1 |

Fixture mode: every model reply is canned, so the full system and the knock-outs that keep its prompts are deterministic, and tokens and cost are zero. The rows marked *mechanics only* ran on a stand-in that plans nothing; they show the harness runs, not what it scores, and are left out of the comparison. The row marked *context only* (no_case_file) sends the model a chat in place of the case file, but the canned replies are scripted against the case file's text, so what they answer to a chat says nothing about what a model would; it is left out of the comparison as well. The live run (`--ai live --yes-spend`) scores them.

## Outcome checks met, by scenario

| Scenario | full | bare | no_planner | no_rule_checks | no_escalation | no_drift_rule | no_case_file | no_evidence_gate | all_tools |
|---|---|---|---|---|---|---|---|---|---|
| Bank debit alert for a planned payment | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Password-protected statement PDF | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Handwritten bill photo | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Hinglish voice note saying "dedh lakh" | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Same invoice by email and by photo | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 0/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Payment returned by the bank | 1/1 | 1/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Missed alert causes drift | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Drift with no explanation | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 0/1 | 1/1 *context only* | 1/1 | 1/1 |
| Vendor email changes bank details | 1/1 | 0/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Hidden instruction in a vendor email | 1/1 | 1/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 0/1 | 0/1 |
| Shortfall week (the worked example) | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| Hidden instruction in an invoice's PDF (fixture-only, not yet run live) | 1/1 | 1/1 *mechanics only* | 1/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| One debit, two bills of the same amount from two vendors (fixture-only, not yet run live) | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| A statement row with a noisy narration (fixture-only, not yet run live) | 1/1 | 0/1 *mechanics only* | 0/1 *mechanics only* | 1/1 | 1/1 | 1/1 | 1/1 *context only* | 1/1 | 1/1 |
| **Outcome success** | 100% | 21% *mechanics only* | 64% *mechanics only* | 93% | 100% | 93% | 100% *context only* | 93% | 93% |
| Model calls | 88 | 28 | 89 | 88 | 107 | 87 | 91 | 87 | 87 |
| Cost µUSD | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Which component earned the most

Knocking out **all_tools, no_drift_rule, no_evidence_gate, no_rule_checks** cost the most: outcome success fell by 7 points from the full system's 100%.

| Knock-out | Drop in outcome success (points) |
|---|---|
| no_rule_checks | 7 |
| no_drift_rule | 7 |
| no_evidence_gate | 7 |
| all_tools | 7 |
| no_escalation | 0 |

## What each knock-out patched

Each is a context manager over named seams (evals/knockouts.py), restored after every run; app code has no ablation flag.

- **no_planner:** `app.jobs.replan.plan`
- **no_rule_checks:** `app.validate.invoice.check_gstin`, `app.validate.invoice.check_invoice_arithmetic`, `app.validate.statement.check_statement_arithmetic`, `app.validate.alert.check_mail_date`, `app.ingest.pipeline._check_bank_details`, `app.ingest.pipeline.check_bank_alert`, `app.ingest.pipeline.check_failure_notice`, `app.ingest.pipeline.check_statement`, `app.ingest.pipeline.check_voice`, `app.ingest.pipeline.check_invoice`, `app.agent.tools.check_bank_alert`, `app.agent.tools.check_invoice`
- **no_escalation:** `app.agent.escalation.start_thinking`, `app.agent.escalation.run_over`, `app.agent.escalation.after_run`
- **no_drift_rule:** `app.jobs.replan.build_snapshot`
- **no_case_file:** `app.agent.loop.next_step`
- **no_evidence_gate:** `app.jobs.run_case.apply_final`
- **all_tools:** `app.agent.tools.TOOLS`, `app.agent.loop.TOOLS`, `app.agent.loop.next_step`
- **no_rule_checks** leaves on the checks that decide whether a record can be read at all: schema, amount parsing, account and sender, statement dates, confidence, voice: the amount was said.
- **bare:** evals/bare.py: one growing chat history, every tool (write tools included) on its own database, no checks, no case file, no escalation, no planner, a cap of 20 steps.
