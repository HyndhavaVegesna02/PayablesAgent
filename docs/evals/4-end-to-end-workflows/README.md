# 4. End-to-end runs

## Full-workflow runs

`make workflow` plays two scripted fortnights, Mon 12 to Sun 25 Oct 2026, through the real web app (owner and
helper logged in, every action a form the page showed, with its CSRF token), the real worker and the demo
clock, each on a freshly seeded database (`evals/workflow.py`, `evals/workflow_runs.py`). Each report is a
step table: what was done, every check, the expected value, the actual one, PASS or FAIL. The reports also
say why each expected value is what it is.

Headline: offline, every check passes; live, A and B each left 1 failed check (`new-decisions` in A, `rows-in-the-ledger-once` in B).

| Report | Mode | What it is |
|---|---|---|
| [workflow-A-2026-10-04.md](workflow-A-2026-10-04.md) | offline | Run A, the worked example: bills by email (with a PDF), photo, voice note and typed entry; the owner confirms, approves, and asks Nandi Foods to pay early; every debit and credit matches (the PF and ESI challan by its payee words; the GST debit, which names no tax office, after the owner links it); the TDD's figures at each step. |
| [workflow-B-2026-10-04.md](workflow-B-2026-10-04.md) | offline | Run B, the bad fortnight: a duplicate invoice, a locked statement, a returned payment, a late alert behind a drift the agent recovers from the mailbox, unexplained debits, a fake bank change, a hidden instruction, a split and an authorised breach. |
| [workflow-A-2026-10-04-live.md](workflow-A-2026-10-04-live.md) | live | Run A once on Gemini. |
| [workflow-B-2026-10-04-live.md](workflow-B-2026-10-04-live.md) | live | Run B once on Gemini. |

## What the live runs showed

- **Workflow A**'s one failed check, `new-decisions`, keyed the voice bill's plan line by the vendor name the
  model read, and the live reading differed from "Sharma Packaging". The bill was in the ledger and planned,
  so this was the harness's keying, not the product. The check now finds that bill by its amount and due date;
  the offline report is regenerated, and the live one is left as it ran. Its voice step reads ₹1,50,000.
- **Workflow B** first failed where the live model left the script's canned path: it read the statement's
  SMS-charges row with no counterparty, and the agent offered its own choices for an unexplained debit. The
  scripted owner now finds a debit by amount and answers by a rule written into the step. In the rerun every
  step runs, and the one failed check left, `rows-in-the-ledger-once`, is the missed counterparty itself: a
  true extraction miss, kept visible. The debit is still counted and explained by its amount.

`make check-evidence` regenerates both offline reports from the code; the live ones are kept as they ran.
