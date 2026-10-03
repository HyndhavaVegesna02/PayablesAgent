# Eval reports

Each folder is one invocation of `make evals` or `make ablation`, written by
`evals/report.py` or `evals/ablation.py`. Every figure in a report comes from
its own `report.json`, and the report's header names the mode, model, prompt
version, config hash, commit and date it came from. Nothing here is typed by
hand.

| Folder | What it is |
|---|---|
| `2026-10-04-fixtures-baseline/` | The 11 TDD scenarios, 5 runs each, fixture mode, on `config.yaml` as committed. |
| `2026-10-04-fixtures-regress-max-steps/` | The same suite with `evals/variants/regress-max-steps.yaml` (the agent's step cap cut from 6 to 2): the regression it catches. |
| `2026-10-04-fixtures-ablation/` | The harness ablation in fixture mode: full system, bare harness, and four knock-outs. |
| `2026-10-04-live-pilot/` | The first live run, 11 scenarios once each on Gemini (PO-authorised): the BEFORE for batch 8's fixes. `traces/` holds the rerun of its two failures with traces kept. |
| `superseded/before-review-round-1/`, `superseded/before-review-round-2/` | The reports as they were before each of batch 7's review rounds, kept and marked; each README says what changed. |

## Full-workflow runs

`make workflow` plays two scripted fortnights, Mon 12 to Sun 25 Oct 2026, through the real web
app (owner and helper logged in, every action a form the page showed, with its CSRF token), the
real worker and the demo clock, each on a freshly seeded database (CHG-027, `evals/workflow.py`,
`evals/workflow_runs.py`). Each report is a step table: what was done, every check, the expected
value, the actual one, PASS or FAIL. The reports also say why each expected value is what it is.

| Report | What it is |
|---|---|
| `workflow-A-<date>.md` | Run A, the worked example: bills by email (with a PDF), photo, voice note and typed entry; the owner confirms, approves, and asks Nandi Foods to pay early; every debit and credit matches (the PF and ESI challan by its payee words; the GST debit, which names no tax office, after the owner links it; CHG-028); the TDD's figures at each step |
| `workflow-B-<date>.md` | Run B, the bad fortnight: a duplicate invoice, a locked statement, a returned payment, a late alert behind a drift the agent recovers from the mailbox, unexplained debits, a fake bank change, a hidden instruction, a split and an authorised breach |

## The regression, told straight (D23)

The step-cap regression first passed every end-to-end check: with 2 steps the
drift case still resolves, because the run at medium runs out and the rerun at
high thinking finishes the job. The end result was right and the path was
worse, at a higher thinking level than the work needs. So scenario 7 also
checks its path: the drift case must be resolved in its first run, at medium
(`drift-resolved-in-its-first-run`, CHG-010a S7). That check is a *trajectory*
check. It is reported in its own Path column and doesn't decide a run's
success (review round 1). The regression report therefore shows scenario 7
succeeding on its end result and failing on its path in every run.
`tests/test_evals.py` keeps both facts.

Two other checks pin the fixture AI's own scripted path (`fixtures_only`): the
agent trying the injected tool in scenario 10, and the medium-then-high run in
scenario 8. A live run leaves them out, since a correct live model may take
another path.

`evals/variants/prompt-degraded.yaml` swaps a "simplified" bank-alert prompt in
for a suite. Canned replies ignore prompts, so only a live run can say whether
the suite catches it. The live reports will sit beside these ones when the
product owner authorises the run (under the budget guard's caps).

## Fixture mode, and what it does not show

In fixture mode every model reply is canned, so runs are deterministic and the
tokens and cost are zero. The reports show that the harness and the code paths
work, not how good the model is. In the ablation, the bare harness and the
no_planner knock-out need replies that no fixture has. They run on a stand-in
that plans nothing, are marked *mechanics only*, and are left out of the
comparison until the live run.
