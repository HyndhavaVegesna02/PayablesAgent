# SME Cash-Flow & Payables Agent — Technical Design Document (MVP)

Version 2.0 · 2 October 2026

> **For Claude Code.** This file has two parts. **Part 1** is the product specification (what the system does). **Part 2** is the build specification (how to build it). Start with Part 2, "How to build from this document", then read Part 1 in full before writing code. Diagrams are Mermaid blocks.

---

# Part 1 — TDD v2.0 (product specification)

## Summary

The agent tells the owner of a small Indian manufacturer which bills he can pay without cash falling below his safety amount. It reads Gmail and owner uploads, keeps its own ledger, plans 14 days ahead, checks that each payment really happened, and re-plans when anything changes.

It never moves money. The owner approves the plan and pays every bill through his own bank app; the agent only watches for the result.

Product definition: an agentic cash-flow planning system that observes a small business's financial activity, keeps a deterministic view of its cash, plans payments against an owner-defined safety amount, surfaces conflicts and options, and re-plans as reality changes. The owner keeps full control of money movement.

This version replaces v1.0 and records the decisions from the 2 October 2026 review. It is an entry for the internal "Beyond the Prompt" hackathon, and all business names in examples are fictional.

Build-level detail is in Part 2 (Implementation architecture): schema, routes, jobs, the agent loop, the Gmail connection and the build order. Both parts use the same names for tables, states, routes and jobs.

## Problem and scope

Small Indian businesses juggle many suppliers, irregular customer payments, statutory dues and thin working capital. Each week the owner decides what to pay now, what can wait, and what happens if a customer pays late. The product covers only this decision layer; it does not replace accounting software.

The loop: observe, understand, plan, find conflicts, ask the owner, observe the outcome, re-plan.

**In scope**

- Gmail as an observation source: bank transaction alerts, bank statements, vendor invoices, sales invoices, tax challans, payment confirmations and failures
- Owner and helper uploads: photos, PDFs, voice notes, typed entries
- Extraction, validation and duplicate detection
- Payables, receivables and payment status tracking
- Several bank accounts combined into one cash position
- A 14-day cash forecast, a payment plan and safety-amount enforcement
- Shortfall detection with owner-selectable options
- Reconciliation of payments, including failures, reversals and balance drift
- Owner settings: safety amount, payment days, planning horizon, priorities, escalation amount, language

**Out of scope**

- Moving money or starting bank payments
- Storing net-banking logins, payment passwords or statement PDF passwords
- Approving payments, contacting customers or vendors, or negotiating on the owner's behalf
- Calculating GST, TDS, PF, ESI or advance tax liability
- Acting as a CA, keeping statutory books, or replacing Tally or Zoho
- Lending, credit or investment decisions, including any credit line or overdraft in the plan
- WhatsApp as an input source
- Owner salary or drawings; the owner does not pay himself from the business accounts
- More than one business per installation
- Treating Gmail as the authoritative bank record
- Legal determinations about MSME status
- Deciding on its own to pay a tax late

## Architecture

AI reads the messy world at the edges; plain code owns every number in the middle. Every financial number shown to the owner comes from deterministic code. The model may extract and explain, but never calculates an authoritative value.

Most of the system is a fixed pipeline, not an agent. Each input is sorted, extracted, validated, written to the ledger, and the plan is recalculated. The model works as an agent only when something does not fit: an unknown transaction, an ambiguous payment match, a balance mismatch, or a failure email that matches no bill.

```mermaid
flowchart TD
    subgraph INPUTS[Inputs]
        GM[Gmail<br/>read-only, filtered senders]
        UP[Uploads<br/>photo, PDF, voice, typed]
        TI[Test inbox<br/>.eml files, demos and evals]
    end
    subgraph PIPE[Pipeline, run on every input]
        SO[Sort<br/>Gemini, low] --> EX[Extract<br/>Gemini, medium] --> VA[Validate<br/>rule checks] --> LE[Ledger<br/>SQLite, events] --> PL[Planner<br/>plain Python]
    end
    GM --> SO
    UP --> SO
    TI --> SO
    LE -- exception --> AG[Exception agent<br/>Gemini, medium or high thinking<br/>tools: search Gmail, read ledger,<br/>run planner, add candidate, ask owner]
    AG -- candidates --> VA
    AG -- questions --> OA[Owner web app<br/>plan, approvals, Needs attention<br/>approve and mark paid run plain code]
    PL -- plan and options --> OA
    OA -- pays approved bills --> BA[Owner's bank app<br/>the agent never sees or moves money]
    BA -. debit or credit alert returns through Gmail .-> GM
```

Payments the owner makes come back as bank alerts through Gmail, which closes the loop. Sort, Extract and the exception agent call Gemini 3.8 Flash; everything else is plain code.

For an exception, the agent gets a small set of tools. It has no tool that approves a payment, marks a bill paid, changes a rule, or sends anything outside the app.

| Tool | What it does | Effect |
| --- | --- | --- |
| search_gmail | Searches the connected mailbox with a query | Read only |
| get_ledger | Reads accounts, transactions, payables and receivables | Read only |
| run_planner | Runs the deterministic planner on current or what-if data | Read only, returns numbers |
| add_candidate | Submits a found transaction or bill to the validation step | Writes a candidate, never the ledger directly |
| ask_owner | Posts a question to the owner's Needs attention list | Writes an in-app question |

The agent's working state lives in a case file: what it is investigating, what it has found, and what is still unknown. A new run starts by reading that file, not the previous conversation.

## Technology stack

One Python codebase, one SQLite file and one AI model. Anyone can clone the repo and run it locally against the test inbox.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python | Both team members use it; strong schema and PDF libraries |
| Web framework | FastAPI | Serves the owner app and upload endpoints from the same codebase |
| Frontend | Jinja templates, HTMX, Pico.css | Server-rendered pages with no React or build step; HTMX updates parts of a page |
| Photos and voice | Browser camera and microphone | No separate mobile app needed |
| Database | SQLite | Single file, no server; one business per installation, with PostgreSQL later if that changes |
| Money | Integers in paise | No floating-point rounding; a small formatter shows lakh style (₹2,82,000) |
| Schemas | Pydantic | Every extracted record is checked before it can reach the ledger |
| AI model | Gemini 3.8 Flash, Google Gen AI Python SDK | One provider for text, images, audio and PDFs |
| Gmail | Gmail API, read-only scope, polled every few minutes | Filtered to known bank and vendor senders |
| Test inbox | Folder of .eml files | Same interface as Gmail; runs without real credentials and holds eval scenarios |
| PDFs | PyMuPDF | Unlocks password-protected statements with a password the owner types each time |
| Planner tests | pytest, Hypothesis | Exact tests plus random bill and cash combinations against the safety rule |
| Evals | Own scenario runner | Runs each AI scenario 5 times and reports success rate and worst case |
| CI | GitHub Actions | Runs tests and evals on every change |
| Traces | JSON Lines files | One line per step, readable without the app |
| Scheduling | APScheduler | Monday plan and Gmail polling |
| Owner alerts | Fixed-template emails sent by code through a separate SMTP account | Keeps the Gmail connection read-only |

## AI model

One model, [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) (`gemini-3.8-flash`), does every AI job; only the thinking level changes. It accepts text, images, audio and PDFs, and supports function calling, structured outputs, and thinking at low, medium or high (`minimal` is not supported and returns an error). No Groq or Claude models are used.

| Job | Input | Thinking | Output |
| --- | --- | --- | --- |
| Sort an incoming email | Headers and body | Low | Bank alert, statement, invoice, challan, payment confirmation, failure, or irrelevant |
| Extract from an email | Body and attachments | Medium | A structured candidate record |
| Extract from a photo or scanned PDF | Image or PDF | Medium | A structured candidate record |
| Read a voice note | Audio | Medium | The transcript and a structured candidate, in one call |
| Handle an exception | Case file and tools | Medium | Findings, candidates, or a question for the owner |
| Handle a complex exception | Case file and tools | High | Same as above |
| Explain the plan | Planner output | Low | A short plain-text summary |

Extraction calls use structured output with a JSON schema generated from the Pydantic models, so the response has the exact shape the validator expects.

**When a case counts as complex.** Code decides, not the model. A case is complex when any of these is true:

- It is not resolved within 6 agent steps
- More is at stake than the escalation amount, which the owner sets in Settings (default ₹50,000)
- An extraction fails validation twice

A case above the escalation amount starts at high thinking; one that hits either of the other rules is rerun at high. If it is still unresolved, it goes to the owner. The trace records which rule triggered.

**If Gemini is unavailable.** The ledger, planner and Monday plan keep working, because they are plain code. New emails and uploads wait in a queue, and the app shows how many are waiting.

**Change control.** The model ID, thinking levels and prompts live in one config file. Any change to them runs the eval suite before it is merged.

## Inputs and validation

Every input becomes a candidate record first. Nothing reaches the ledger until it passes the schema check and every rule check below.

| Source | Arrives through | Notes |
| --- | --- | --- |
| Bank transaction alerts | Gmail | Fastest signal; most include the available balance |
| Bank statements | Gmail PDF attachment | Preferred for reconciliation; often password-protected |
| Vendor invoices, sales invoices, tax challans | Gmail or upload | PDF, image or email body |
| Invoice photos | Web app, phone camera | Includes handwritten bills |
| Voice notes | Web app, microphone | Hindi, English or Hinglish |
| Typed entries | Web app form | For anything without a document |
| Test inbox | Folder of .eml files | Same interface as Gmail, used for demos and evals |

**Gmail rules.** The connection uses read-only access. A search filter limits fetching to known bank and vendor senders, and each record keeps its Gmail message ID as its source reference. The owner connects Gmail once through Google's consent screen; in Google's Testing mode the connection lasts 7 days, after which the app asks him to reconnect. The full steps are in Part 2, "Gmail ingestion".

**Password-protected statements.** PyMuPDF unlocks the PDF using a password the owner types when the statement arrives. The password is used once and never stored.

**Rule checks (plain code, run on every candidate)**

- Schema: the record matches its Pydantic model
- GSTIN: correct format and a valid check digit
- Invoice arithmetic: line items plus GST equal the invoice total
- Statement arithmetic: opening balance plus credits minus debits equals the closing balance
- Dates: the invoice date is on or before the due date
- Duplicates: same vendor and invoice number, or same amount, date and reference
- Confidence: fields the model marks as uncertain are flagged for the owner

**Owner confirmation.** A bill from a photo, PDF or voice note becomes CONFIRMED only after the owner checks it. Voice entries show the transcript beside the extracted bill. Strong rule checks keep corrections rare, so confirming does not turn into rubber-stamping.

## Data model

The core tables below use the exact names from the SQLite schema in Part 2, which is authoritative for every column and constraint. Every amount is an integer in paise, and every change also writes a row to `event`.

| Table | Key columns |
| --- | --- |
| business | id, name, timezone, safety_amount_paise, escalation_stake_paise, horizon_days, payment_days, language |
| app_user | id, business_id, email, role (owner or helper), password_hash |
| party | id, kind (vendor, customer or both), name, gstin, aliases_json, bank_account_mask, bank_ifsc, bank_status |
| bank_account | id, bank_name, account_name, account_mask, alert_senders_json, opening_balance_paise, opening_balance_at, reported_balance_paise, reported_at, drift_status, last_reconciled_at |
| account_balance (view) | account_id, calculated_balance_paise, computed from bank_txn and never stored |
| bank_txn | id, account_id, direction, amount_paise, txn_date, value_date, counterparty, party_id, reference, balance_after_paise, dedup_key, source_document_id, status |
| payable | id, party_id, invoice_number, invoice_date, amount_paise, due_date, priority, grace_days, discount_paise, discount_by, parent_payable_id, status, planned_date, approved_by, matched_txn_id, version |
| receivable | id, party_id, invoice_number, amount_paise, due_date, expected_date, confidence, matched_txn_id, version |
| tax_obligation | id, tax_type, period, due_date, amount_paise, amount_status, payable_id, challan_document_id |
| event | id, occurred_at, actor, event_type, entity, entity_id, before_json, after_json, reason, source_ref, trace_run_id |

The schema also holds source_document, candidate, plan_run, plan_line, plan_day, shortfall_option, agent_case, owner_question, job, sync_state and gmail_connection. `bank_txn.status` is UNMATCHED, MATCHED, EXPLAINED, ADJUSTMENT or REVERSED.

Value sets:

- `receivable.confidence`: CONFIRMED (received), COMMITTED (customer gave a date in writing), EXPECTED (usual pattern only), UNKNOWN
- `tax_obligation.amount_status`: CONFIRMED, ESTIMATED, MISSING
- `bank_account.drift_status`: OK, CHECKING, ASK_OWNER
- `payable.priority`: statutory, critical, normal, flexible

## Payment states

A payable moves through eight states, and a bill marked PAID never silently disappears. It reopens if the payment is reversed, bounced or returned.

A re-plan moves a PLANNED bill back to CONFIRMED when its decision changes to WAIT. A bill the owner splits becomes SPLIT, and each of its two parts follows the same states.

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> CONFIRMED: owner confirms
    CONFIRMED --> PLANNED: planner PAY
    PLANNED --> CONFIRMED: planner WAIT
    CONFIRMED --> SPLIT: owner splits
    PLANNED --> SPLIT: owner splits
    PLANNED --> PAYMENT_EXPECTED: owner approves
    PAYMENT_EXPECTED --> PAID: matched or marked paid
    PAYMENT_EXPECTED --> REVIEW: match unclear
    PAYMENT_EXPECTED --> REOPENED: payment failed
    REVIEW --> PAID: owner says paid
    REVIEW --> REOPENED: owner says failed
    PAID --> REOPENED: reversed or returned
    REOPENED --> PLANNED: planner re-plans
```

Only the owner or a matched bank debit can make a bill PAID; the AI moves no state on its own. The full transition table, with the actor allowed for each move, is in Part 2, "Ledger writer".

## Reconciliation and balance drift

The ledger keeps three views apart: observed (what the evidence shows happened), planned (what was meant to happen) and forecast (what is expected next). Reconciliation compares observed against planned.

**Matching a payment.** A debit matches a PAYMENT_EXPECTED payment when the account, amount and counterparty agree within 3 days of the planned date. The match is plain code. An ambiguous match moves the payment to REVIEW and opens an exception case.

**Failures and reversals.** A failure, bounce or return email moves the payment to REOPENED. The planner recalculates and the owner is told.

**Unexpected transactions.** A debit or credit that matches nothing in the plan opens an exception case. The agent searches Gmail and the ledger for context, then asks the owner what it was.

**Balance drift.** If a bank alert never reaches Gmail, the calculated balance drifts from the real one. The agent handles it in three steps:

1. Spot the gap. Compare the bank-reported balance, from an alert's available balance or a statement's closing balance, with the calculated balance for that account.
2. Recheck Gmail. The agent searches that account's emails for the period. Any missed transaction it finds goes through validation into the ledger, and the gap closes.
3. Ask the owner. If a gap remains, the owner sees both figures and the difference. His answer becomes the new starting balance, and the unexplained difference is recorded as an adjustment event.

While drift is unresolved, the planner uses the lower of the two balances. An open mismatch can never make the safety check look better than it is.

## Planning

The planner is plain Python. It projects a balance for every day of the 14-day horizon and keeps every day at or above the safety amount.

```latex
\text{Projected}(d) = \text{Observed cash} + \sum_{t \le d} \text{Counted inflows}_t - \sum_{t \le d} \text{Planned outflows}_t - \sum_{t \le d} \text{Known commitments}_t
```

Observed cash is the sum across all bank accounts, using the lower figure for any account with unresolved drift. CONFIRMED receivables are already in the bank balance, so counted inflows are only COMMITTED receivables dated inside the horizon. EXPECTED and UNKNOWN ones are shown but not counted.

**The safety rule.** In a normal plan, the projected balance is at least the safety amount on every day. A plan that cannot meet this is invalid, and the planner escalates instead of choosing.

**How bills are ordered.** Statutory first, then critical, normal and flexible. Within a level, bills are ordered by due date. Each bill targets the latest payment day on or before its due date, or its discount date if that saves money; grace days are used only when the owner chooses the delay option. Payments fall only on the owner's payment days.

**Output.** Each payable gets PAY (with a date), WAIT, or ESCALATE, plus a one-line reason. The plan is built every Monday and rebuilt after any material change.

**Shortfalls.** When the safety rule cannot be met, the agent lists the options and the planner computes the result of each. The owner chooses; the agent never picks.

1. Ask a customer to pay earlier, by the last weekday before the payment day that precedes the shortfall (Friday at the latest; Saturdays are not used)
2. Ask a supplier to split a payment
3. Delay a flexible payment within its grace days
4. Explicitly authorise going below the safety amount
5. Send a statutory question to the CA

**Taxes.** GST, TDS, PF, ESI and advance tax are fixed-date bills with amounts supplied by the CA, and each becomes a statutory payable in the ledger. Each amount is CONFIRMED, ESTIMATED or MISSING, and estimates are labelled wherever they appear. The agent reminds the owner, flags missing challans, and never decides on its own that a statutory payment should wait.

## Owner web app

The owner works in a mobile-first web app with five screens. Every approve, confirm or mark-paid button calls plain code directly, never the AI. An approval is refused if the plan has changed since the owner opened it.

- This week: payments by day, the lowest projected balance against the safety amount, and approve buttons
- Needs attention: agent questions, bills to confirm, balance mismatches, shortfall options
- Add: photo, PDF, voice note or typed entry
- Accounts: each bank balance, its drift status, and the Gmail connection
- Settings: safety amount, payment days, horizon, priorities, escalation amount, language (owner only)

**Messages.** The agent speaks only when action or awareness is needed. AI-written text is shown as plain text, so content from a vendor email cannot inject links or buttons.

| Trigger | Example message |
| --- | --- |
| Monday plan with a shortfall | Your 14-day plan is ready. Lowest projected balance ₹1.83L on Thu 22 Oct, ₹67K below your safety amount. Choose an option. |
| Money received | ₹2,00,000 received from Nandi Foods. Lowest projected balance is now ₹3.83L. Plan updated. |
| Payment failed | Prime Chem's ₹1,20,000 payment was returned. The bill is reopened and the plan updated. |
| Unexpected debit | A ₹32,000 debit from HDFC wasn't in the plan. What was it for? |
| Balance mismatch | HDFC shows ₹4,12,000; I calculate ₹4,44,000. Difference ₹32,000. What is the actual balance? |

**Alerts outside the app.** When something needs the owner, code sends a fixed-template email to his registered address with a link into the app. It goes through a separate SMTP account, and the AI cannot choose the recipient or the wording.

**Roles.** The server checks the role on every action, not only in the page.

| Action | Owner | Helper |
| --- | --- | --- |
| Submit bills, invoices, photos, voice notes | Yes | Yes |
| Confirm an extracted bill | Yes | No |
| Approve the plan or choose a shortfall option | Yes | No |
| Mark a payment paid | Yes | No |
| Answer questions about unexpected transactions | Yes | No |
| Approve a change to a vendor's bank details | Yes | No |
| Change the safety amount, escalation amount, payment days or rules | Yes | No |
| Override the safety amount or make a statutory exception | Yes | No |
| See the plan, balances and alerts | Yes | No; only his own submissions and their status |
| Connect or disconnect Gmail | Yes | No |

## Security and threat model

A hijacked model cannot move money or approve anything, because the AI has no tool that does either. The worst a malicious email can do is put a wrong candidate in front of the owner.

**Principles**

- Never store bank logins, payment passwords or statement PDF passwords
- Never execute payments
- Gmail access is read-only and limited to filtered senders
- Encrypt sensitive data at rest, including the Gmail refresh token; access tokens are never stored
- Isolate each business's data and check roles on the server
- Record every financial-state change and keep a source reference for every extracted record

**The three risky ingredients.** Danger comes when one agent has private data, reads untrusted content, and can send messages out. This agent has the first two: financial records, and emails and invoices from anyone. It lacks the third, because it cannot send anything outside the app and owner alerts are fixed templates sent by code.

**Confirmation happens outside the agent.** The owner pays in his own bank app, which the agent cannot see or control. Approvals in the web app are buttons wired to plain code.

| Threat | Defence |
| --- | --- |
| Fake vendor email changes bank details | Marked as a material vendor banking change; only the owner can approve it |
| Email text tells the agent to mark a bill urgent or pay today | Priority and payment dates are set by the planner and owner, not by extracted text; the AI has no approve tool |
| Injected text tries to reach the owner's screen | All AI text is shown as plain text |
| Forged or duplicate invoice | Duplicate check, GSTIN check digit and invoice arithmetic |
| Spoofed bank alert | Statement arithmetic and drift check against the next statement |
| Helper account misused | Helpers can only submit; every other action is owner-only |

**Attack to run and document.** Plant two emails in the test inbox: one changing a vendor's bank details, one with hidden text telling the agent to mark a bill urgent. Record what the agent did, what reached the owner, and whether any defence failed.

## Traces and audit trail

The system keeps two separate records. The trace tells an engineer what the agent did; the audit trail tells the business what changed in its money.

**Trace.** One JSON Lines file per run, one line per step. Someone who did not build the agent should be able to explain a failure from the trace alone.

| Field | Contents |
| --- | --- |
| run_id, step, timestamp | Which run, which step, when |
| input_ref | Gmail message ID or upload ID that started the run |
| model, thinking | Model ID and thinking level used |
| tool, arguments, result | Each tool call and a summary of what came back |
| validation | Which rule checks passed or failed |
| retries | Number of retries and their causes |
| escalation_rule | The rule that made a case complex, if any |
| tokens, cost | Input and output tokens and cost for the step |

**Audit trail.** The append-only `event` table records every financial-state change. Each event links back through validation and extraction to its source, so any number can be traced from email to plan.

Example event:

- Event: PAYMENT_PLANNED
- Bill: Prime Chem / INV-123, ₹1,20,000
- Date: Thu 22 Oct 2026
- Reason: due date falls on a payment day
- Projected minimum balance: ₹3,83,000
- Safety amount: ₹2,50,000
- Rule check: PASSED

## Evaluation

Evals run at three levels: did the task succeed, was the path sound, and which part broke when it failed. Every AI scenario runs 5 times, and the report gives the success rate, the spread and the worst case.

**Planner tests (pytest and Hypothesis).** Exact tests for known cases, plus random bills, dates and balances checked against invariants:

- A normal plan never projects a day below the safety amount
- A PAID bill never disappears; it is either PAID or REOPENED
- Every rupee in the forecast traces to a ledger record
- Unresolved drift always uses the lower balance

**Scenario suite (test inbox and uploads)**

| Scenario | Passes when |
| --- | --- |
| Bank debit alert for a planned payment | Transaction extracted and matched; payment moves to PAID |
| Password-protected statement PDF | Unlocked, rows extracted, statement arithmetic passes |
| Handwritten bill photo | Fields extracted; GSTIN and totals checked |
| Hinglish voice note saying "dedh lakh" | Amount extracted as ₹1,50,000 and shown with the transcript |
| Same invoice by email and by photo | One payable, not two |
| Payment returned by the bank | Bill REOPENED, plan rebuilt, owner told |
| Missed alert causes drift | Gap found, transaction recovered from Gmail, gap closed |
| Drift with no explanation | Owner asked; planner uses the lower balance meanwhile |
| Vendor email changes bank details | Flagged as owner-only; nothing changes without approval |
| Hidden instruction in a vendor email | No change to priority, dates or payment status |
| Shortfall week (the worked example) | Lowest balance ₹1,83,000 found; options computed as in the worked example |

Planner tests run on every push in GitHub Actions. All code reads time through a Clock, so the scenario suite replays a fortnight in seconds. The scenario suite runs on every change to prompts, model settings or extraction code.

**Harness comparison (required).** Keep Gemini 3.8 Flash fixed and run the scenario suite twice. The bare version exposes all tools, skips the rule checks, has no escalation rules or case file, and lets the model calculate balances and plans itself. The full version is the system above. Report the difference, and which component added the most: the planner, the rule checks, the escalation rules or the drift rule.

**Reusable component.** Candidate to share with other teams: the Indian finance validators (GSTIN check digit, invoice arithmetic, statement arithmetic) as a standalone Python package.

## Worked example

The Monday plan finds the balance would fall to ₹1,83,000 on Thu 22 Oct, ₹67,000 below the safety amount. Nandi Foods paying early fixes it, lifting the lowest balance to ₹3,83,000. Every figure below reconciles, so this example doubles as a planner golden test and as the seed data.

Setup: Mon 12 Oct 2026, observed cash ₹6,20,000, safety amount ₹2,50,000, payment days Monday and Thursday, horizon 12 to 25 Oct.

| Date | Item | Amount | Notes |
| --- | --- | --- | --- |
| Mon 12 Oct | Paper supplier | −₹1,80,000 | Normal; due 14 Oct |
| Tue 13 Oct | Kaveri Traders receipt | +₹33,000 | COMMITTED, so counted |
| Thu 15 Oct | PF and ESI | −₹45,000 | Statutory; due 15 Oct; ESTIMATED by the CA |
| Thu 15 Oct | Electricity | −₹35,000 | Critical; due 16 Oct |
| Mon 19 Oct | GST | −₹90,000 | Statutory; due 20 Oct; CONFIRMED by the CA |
| Thu 22 Oct | Prime Chem | −₹1,20,000 | Normal; due 22 Oct; no grace days |
| Wed 28 Oct | Nandi Foods receipt | +₹2,00,000 | EXPECTED and outside the horizon, so not counted |

The planner marks the four earlier payments PAY and Prime Chem ESCALATE, because paying it takes the balance to ₹1,83,000.

Projected end-of-day balance (golden values for the planner test):

| Date | Original plan | Nandi Foods pays on Fri 16 Oct |
| --- | --- | --- |
| Mon 12 Oct | ₹4,40,000 | ₹4,40,000 |
| Tue 13 Oct | ₹4,73,000 | ₹4,73,000 |
| Wed 14 Oct | ₹4,73,000 | ₹4,73,000 |
| Thu 15 Oct | ₹3,93,000 | ₹3,93,000 |
| Fri 16 Oct | ₹3,93,000 | ₹5,93,000 |
| Sat 17 Oct | ₹3,93,000 | ₹5,93,000 |
| Sun 18 Oct | ₹3,93,000 | ₹5,93,000 |
| Mon 19 Oct | ₹3,03,000 | ₹5,03,000 |
| Tue 20 Oct | ₹3,03,000 | ₹5,03,000 |
| Wed 21 Oct | ₹3,03,000 | ₹5,03,000 |
| Thu 22 Oct | ₹1,83,000 | ₹3,83,000 |
| Fri 23 Oct | ₹1,83,000 | ₹3,83,000 |
| Sat 24 Oct | ₹1,83,000 | ₹3,83,000 |
| Sun 25 Oct | ₹1,83,000 | ₹3,83,000 |

Only the 22 Oct payment to Prime Chem breaks the rule; the four earlier payments stay clear of it.

**Options the planner computed**

| Option | Lowest balance | Meets the rule? |
| --- | --- | --- |
| Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct | ₹3,83,000 on 22 Oct | Yes |
| Split Prime Chem: ₹53,000 on 22 Oct, ₹67,000 after 25 Oct | ₹2,50,000 on 22 Oct | Yes, exactly |
| Authorise going below the safety amount | ₹1,83,000 on 22 Oct | No, ₹67,000 below |

Delaying a flexible bill does not apply, because no bill this fortnight is flexible. No statutory question arises, so nothing goes to the CA.

**What happens next.** The owner chooses the first option and calls Nandi Foods himself. Nandi pays on Fri 16 Oct, the HDFC credit alert arrives in Gmail, and the receipt is matched and marked CONFIRMED. The planner reruns, the lowest balance becomes ₹3,83,000, and Prime Chem moves to PAY on Thu 22 Oct.

## Definition of done

A test business, running on the test inbox, can do all of the following end to end without the builders in the room.

- [ ] Connect several bank accounts through their email alerts and statements
- [ ] Submit bills and sales invoices by photo, PDF, voice note or text
- [ ] Extract, validate and confirm them into the ledger
- [ ] Configure the safety amount, payment days and horizon
- [ ] Produce a 14-day forecast and payment plan
- [ ] Detect a shortfall and show computed options
- [ ] Receive the owner's approval or choice
- [ ] Detect the payment the owner made in his bank app and match it to the plan
- [ ] Detect a failed or reversed payment, reopen the bill and re-plan
- [ ] Detect balance drift, recover from Gmail or ask the owner
- [ ] Explain why the plan changed
- [ ] Keep a complete audit trail

**Hackathon deliverables**

- [ ] Repository and README that someone else can run
- [ ] Architecture diagram with loop, tools, context handling and controls labelled
- [ ] Two traces: one success, one failure
- [ ] Eval report with repeated runs, one caught regression and the harness comparison
- [ ] One-page threat model with the documented attack
- [ ] Permission model for the agent's tools
- [ ] 3-minute demo video
- [ ] Reusable component flagged

## Decisions log

| Date | Decision |
| --- | --- |
| 2 Oct 2026 | Gmail connects once through OAuth with read-only access; a refused token marks Gmail disconnected and asks the owner to reconnect |
| 2 Oct 2026 | The escalation amount is an owner setting, default ₹50,000; each change is recorded as an event |
| 2 Oct 2026 | Implementation refinements folded into this TDD: computed balances, receivable counting, SPLIT state, re-plan to WAIT, stale approvals refused, taxes as payables |
| 2 Oct 2026 | Only COMMITTED receivables count in the forecast; CONFIRMED ones are already in the bank balance |
| 2 Oct 2026 | One business per installation for the MVP |
| 2 Oct 2026 | The owner does not pay himself from the business accounts; no drawings handling |
| 2 Oct 2026 | Debits match planned payments within 3 days of the planned date |
| 2 Oct 2026 | Early-payment requests use weekdays only, Friday at the latest; Saturdays are not counted |
| 2 Oct 2026 | Gemini 3.8 Flash handles every AI job; no Groq or Claude models |
| 2 Oct 2026 | Code rules decide when a case is complex; complex cases rerun at high thinking, then go to the owner |
| 2 Oct 2026 | Python, FastAPI, Jinja, HTMX and Pico.css for the app; SQLite for the database |
| 2 Oct 2026 | Balance drift: compare, recheck Gmail, then ask the owner; plan on the lower balance meanwhile |
| 2 Oct 2026 | Credit line and WhatsApp removed from scope |
| 2 Oct 2026 | Statement PDF passwords typed per statement, never stored |
| 2 Oct 2026 | The AI gets no approve, mark-paid or outbound-message tool |
| 2 Oct 2026 | Worked example recomputed so every figure reconciles |

## Open questions

- Are 6 steps and a ₹50,000 default escalation amount the right starting points? Revisit once the first eval runs are in.

## Sources

- [Gemini 3.8 Flash model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), Google AI for Developers
- SME Cash-Flow & Payables Agent TDD v1.0 (uploaded)
- Beyond the Prompt hackathon brief (uploaded)

---

# Part 2 — Implementation architecture (build specification)

## How to build from this document

Part 2 is the build specification; Part 1 is the product specification. Read both before writing code.

- Names are exact. Tables, columns, states, job kinds, routes, config keys and tool names must match Part 2 character for character.
- Part 2 decides code-level detail: names, schema, algorithms. Part 1 decides product behaviour. If they disagree, stop and ask instead of choosing.
- Build in the order of the MVP build sequence. A phase is done only when its exit test passes in CI.
- Do not add features, tables, routes or dependencies that are not written here; propose them first.
- Money is integer paise everywhere. No float ever holds an amount.
- Every state change goes through `ledger.writer.transition()`. Nothing else updates a state column.
- Part 1's worked example is both the first golden test and the seed data.
- Use only the test inbox and seed data; no real financial data.

| Command | What it does |
| --- | --- |
| make setup | Creates the virtual environment and installs dependencies |
| make db | Creates or migrates the SQLite file |
| make seed | Loads the worked-example business, accounts, parties, bills and test inbox |
| make run | Starts the web process on port 8000 |
| make worker | Starts the worker and scheduler |
| make test | Runs pytest, Hypothesis and import-linter |
| make evals | Runs the scenario suite 5 times per scenario and writes the report |
| make ablation | Runs the harness comparison |

## Summary

Two processes share one SQLite file: a FastAPI web process and a worker that runs jobs. Everything else is Python modules in one repository, with no separate services to deploy. The AI sits behind one function, and the planner, rule checks and ledger writer are code paths the AI cannot reach.

**What this design adds to the TDD**

| Area | Refinement | Why |
| --- | --- | --- |
| Balances | The calculated balance is a SQL view over transactions, not a stored column | It can never disagree with the transactions |
| Receivables | CONFIRMED receivables are already in bank cash; the forecast adds only COMMITTED receivables with a future date | The earlier wording would count received money twice |
| States | New transition PLANNED to CONFIRMED when a re-plan changes PAY to WAIT | The earlier diagram had no way back |
| Splits | Splitting a bill marks it SPLIT and creates two child payables, each following the state machine | Keeps one state machine |
| Taxes | Each tax obligation creates a statutory payable | The planner only ever sees payables |
| Escalation | The escalation amount, an owner setting with a ₹50,000 default, is checked when a case opens; cases above it start at high thinking | No point running medium first |
| Approvals | Approving checks that the plan is still current; a stale plan is refused | The owner never approves numbers he did not see |
| Time | All code reads time through a Clock interface | Evals replay a fortnight in seconds |
| Matching window | 3 days either side of the planned date, in config | Agreed on 2 Oct 2026 |
| Owner's own transfers | None to handle: the owner does not pay himself from the business accounts | Agreed on 2 Oct 2026; no drawings rule needed |
| Installations | One business per installation for the MVP | Agreed on 2 Oct 2026; keeps login, Gmail and settings simple |

These refinements are also written into Part 1.

## At a glance

```mermaid
flowchart TD
    BR[Owner's browser<br/>phone, mobile-first]
    GMX[Gmail<br/>or test inbox]
    GEM[Gemini 3.8 Flash]
    SMTP[SMTP<br/>owner alerts]

    subgraph WEB[Web process - FastAPI]
        RT[routes<br/>pages and HTMX actions]
        AU[auth and roles<br/>checked on every route]
        UPL[uploads<br/>store, then queue a job]
    end

    subgraph WRK[Worker process]
        MS[mail source<br/>Gmail or .eml]
        AIC[ai.client<br/>the only AI call]
        NT[notify<br/>fixed templates]
        PIPE[pipeline<br/>sort to route]
        REC[reconciler<br/>match and drift]
        SCH[scheduler<br/>Monday, polling]
        JR[job runner<br/>claims, retries]
        AGL[agent loop<br/>exceptions only]
    end

    subgraph CORE[Shared core, used by both processes]
        WR[ledger.writer<br/>the only writer]
        RD[db/read.py<br/>read-only connection]
        PLN[planner<br/>pure function]
        DOM[domain<br/>types and states]
    end

    DB[(SQLite file, WAL mode<br/>ledger, plans, jobs, events)]

    BR --> WEB
    MS --> GMX
    AIC --> GEM
    NT --> SMTP
    WEB -- owner actions, reads --> CORE
    WRK -- writes, plans, reads --> CORE
    CORE --> DB
```

The web process never calls Gemini; it writes owner actions through the ledger writer and leaves everything slow to the worker. Only `pipeline`, `agent loop` and `ai.client` use Gemini.

## Repository layout

Each folder under `app/` is one module with one job. The dependency rules below are checked in CI with import-linter, so a broken boundary fails the build rather than a code review.

```text
cashflow-agent/
  app/
    main.py              FastAPI app factory
    worker.py            job worker + APScheduler entry point
    config.py            settings, model config, thresholds
    clock.py             Clock interface: SystemClock, FakeClock
    domain/              pure types, no I/O
      money.py           Paise type, lakh formatter
      models.py          Pydantic models for every record
      states.py          allowed transitions table
    db/
      schema.sql
      migrations/        numbered .sql files, applied in order
      read.py            read-only queries (separate connection, mode=ro)
    ledger/
      writer.py          the only code that writes ledger tables and events
      reconcile.py       payment matching, failures, drift
    planner/
      forecast.py        daily balance projection
      plan.py            plan(snapshot) -> PlanResult
      options.py         shortfall options as what-if runs
      diff.py            what changed between two plan runs
    ingest/
      mail_source.py     MailSource protocol
      gmail.py           GmailSource (read-only scope)
      gmail_oauth.py     connect, callback, revoke
      eml_folder.py      EmlFolderSource (test inbox)
      uploads.py         photo, PDF, voice, typed
      pdf.py             PyMuPDF unlock
      pipeline.py        sort -> extract -> validate -> route
    validate/
      gstin.py  invoice.py  statement.py  dates.py  duplicates.py
    ai/
      client.py          the one function that calls Gemini
      prompts/           versioned prompt files
      sort.py  extract.py  voice.py  explain.py
    agent/
      loop.py  tools.py  case_file.py  escalation.py
    web/
      routes/  templates/  static/ (pico.min.css, htmx.min.js)
    notify/
      smtp.py  templates/
    jobs/
      queue.py           SQLite-backed job table
    trace/
      tracer.py  view.py
  evals/
    scenarios/<name>/    .eml files, uploads, expected.yaml
    runner.py  ablation.py  report.py
  tests/
  fixtures/test_inbox/
  fixtures/seed.py       loads the worked-example business
  .env.example
  Makefile
  pyproject.toml
  README.md
```

**Dependency rules**

- `domain` imports nothing else from `app`
- `planner` imports only `domain`, so it is a pure function of its input
- `ai` never imports `ledger`, `db` or `web`
- `agent` reaches the database only through `db/read.py` and two narrow insert functions, for candidates and owner questions
- Only `ledger/writer.py` updates ledger tables or the state of a payable, receivable or transaction
- `web` calls `ledger.writer` for owner actions and never calls `ai` directly

## Dependencies and environment

Python 3.12, managed with uv and `pyproject.toml`; versions are pinned in the lock file at build time. HTMX and Pico.css are vendored into `web/static/`, so the app runs without a CDN.

- Runtime: fastapi, uvicorn, jinja2, python-multipart, itsdangerous, argon2-cffi, pydantic, pydantic-settings, pyyaml, apscheduler, google-genai, google-api-python-client, google-auth, google-auth-oauthlib, pymupdf, cryptography
- Development: pytest, hypothesis, import-linter, httpx

| Variable | Purpose |
| --- | --- |
| GEMINI_API_KEY | Gemini API access |
| GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET | OAuth client from Google Cloud |
| GOOGLE_REDIRECT_URI | For example http://localhost:8000/gmail/callback |
| FERNET_KEY | Encrypts stored emails, uploads and the Gmail refresh token |
| SESSION_SECRET | Signs the session cookie |
| SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_FROM | Owner alert emails |
| DATABASE_PATH | SQLite file location |
| DATA_DIR | Encrypted documents and uploads |
| TRACE_DIR | JSON Lines traces |
| MAIL_SOURCE | gmail or eml_folder |
| TEST_INBOX_PATH | Folder of .eml files when MAIL_SOURCE is eml_folder |

`.env.example` lists every variable with an empty value; `.env` is git-ignored.

## Database schema

Twenty tables and one view in one SQLite file, in WAL mode so the web process and the worker can work at the same time. Amounts are integers in paise, dates are ISO strings in Asia/Kolkata, and the event table refuses updates and deletes.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- Business and people
CREATE TABLE business (                 -- one row only: one business per installation
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  safety_amount_paise INTEGER NOT NULL CHECK (safety_amount_paise >= 0),
  escalation_stake_paise INTEGER NOT NULL DEFAULT 5000000
    CHECK (escalation_stake_paise >= 0),   -- owner setting, ₹50,000 default
  horizon_days INTEGER NOT NULL DEFAULT 14,
  payment_days TEXT NOT NULL DEFAULT 'MON,THU',
  language TEXT NOT NULL DEFAULT 'en'
);

CREATE TABLE app_user (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('owner','helper')),
  password_hash TEXT NOT NULL           -- Argon2
);

CREATE TABLE party (                    -- vendors and customers
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  kind TEXT NOT NULL CHECK (kind IN ('vendor','customer','both')),
  name TEXT NOT NULL,
  gstin TEXT,
  aliases_json TEXT NOT NULL DEFAULT '[]',  -- names seen in bank alerts, added only after owner confirms
  bank_account_mask TEXT,
  bank_ifsc TEXT,
  bank_status TEXT NOT NULL DEFAULT 'none'
    CHECK (bank_status IN ('none','verified','change_pending'))
);

CREATE TABLE bank_account (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  bank_name TEXT NOT NULL,
  account_name TEXT NOT NULL,
  account_mask TEXT NOT NULL,
  alert_senders_json TEXT NOT NULL DEFAULT '[]',
  opening_balance_paise INTEGER NOT NULL,
  opening_balance_at TEXT NOT NULL,
  reported_balance_paise INTEGER,
  reported_at TEXT,
  drift_status TEXT NOT NULL DEFAULT 'OK'
    CHECK (drift_status IN ('OK','CHECKING','ASK_OWNER')),
  last_reconciled_at TEXT,
  status TEXT NOT NULL DEFAULT 'active'
);

-- Evidence
CREATE TABLE source_document (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  kind TEXT NOT NULL CHECK (kind IN ('email','photo','pdf','voice','typed')),
  external_ref TEXT,                    -- Gmail message ID or upload ID
  content_sha256 TEXT NOT NULL,
  received_at TEXT NOT NULL,
  submitted_by INTEGER REFERENCES app_user(id),
  storage_path TEXT,                    -- encrypted file on disk
  doc_type TEXT,                        -- set by the sort step
  status TEXT NOT NULL DEFAULT 'NEW'
    CHECK (status IN ('NEW','LOCKED','PROCESSED','IRRELEVANT','FAILED')),
  UNIQUE (business_id, content_sha256),
  UNIQUE (business_id, kind, external_ref)
);

CREATE TABLE candidate (
  id INTEGER PRIMARY KEY,
  source_document_id INTEGER NOT NULL REFERENCES source_document(id),
  record_type TEXT NOT NULL
    CHECK (record_type IN ('txn','payable','receivable','tax','statement')),
  payload_json TEXT NOT NULL,
  transcript TEXT,                      -- voice notes only
  model_id TEXT, thinking TEXT, prompt_version TEXT,
  checks_json TEXT,                     -- result of every rule check
  status TEXT NOT NULL
    CHECK (status IN ('NEW','VALID','INVALID','AWAITING_OWNER','ACCEPTED','REJECTED')),
  attempts INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL,             -- 'pipeline' or 'agent:case:<id>'
  created_at TEXT NOT NULL
);

-- Ledger
CREATE TABLE bank_txn (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES bank_account(id),
  direction TEXT NOT NULL CHECK (direction IN ('debit','credit')),
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
  txn_date TEXT NOT NULL,
  value_date TEXT,
  description TEXT,
  counterparty TEXT,
  party_id INTEGER REFERENCES party(id),
  reference TEXT,
  balance_after_paise INTEGER,          -- available balance in the alert, if shown
  dedup_key TEXT NOT NULL UNIQUE,       -- built by code from account, date, amount, reference
  source_document_id INTEGER REFERENCES source_document(id),
  candidate_id INTEGER REFERENCES candidate(id),
  status TEXT NOT NULL
    CHECK (status IN ('UNMATCHED','MATCHED','EXPLAINED','ADJUSTMENT','REVERSED'))
);

CREATE TABLE payable (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  party_id INTEGER REFERENCES party(id),
  invoice_number TEXT,
  invoice_date TEXT,
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
  due_date TEXT NOT NULL,
  priority TEXT NOT NULL
    CHECK (priority IN ('statutory','critical','normal','flexible')),
  grace_days INTEGER NOT NULL DEFAULT 0,
  discount_paise INTEGER,
  discount_by TEXT,
  parent_payable_id INTEGER REFERENCES payable(id),  -- set on a split
  source_document_id INTEGER REFERENCES source_document(id),
  status TEXT NOT NULL CHECK (status IN
    ('DRAFT','CONFIRMED','PLANNED','PAYMENT_EXPECTED','PAID','REOPENED','REVIEW','SPLIT')),
  planned_date TEXT,
  approved_by INTEGER REFERENCES app_user(id),
  approved_at TEXT,
  matched_txn_id INTEGER REFERENCES bank_txn(id),
  version INTEGER NOT NULL DEFAULT 1   -- optimistic locking
);

CREATE TABLE receivable (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  party_id INTEGER REFERENCES party(id),
  invoice_number TEXT,
  invoice_date TEXT,
  amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
  due_date TEXT,
  expected_date TEXT,
  confidence TEXT NOT NULL
    CHECK (confidence IN ('CONFIRMED','COMMITTED','EXPECTED','UNKNOWN')),  -- CONFIRMED = received and matched
  matched_txn_id INTEGER REFERENCES bank_txn(id),
  source_document_id INTEGER REFERENCES source_document(id),
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE tax_obligation (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  tax_type TEXT NOT NULL CHECK (tax_type IN ('GST','TDS','PF','ESI','ADVANCE_TAX')),
  period TEXT NOT NULL,
  due_date TEXT NOT NULL,
  amount_paise INTEGER,
  amount_status TEXT NOT NULL
    CHECK (amount_status IN ('CONFIRMED','ESTIMATED','MISSING')),
  payable_id INTEGER REFERENCES payable(id),   -- the statutory payable this creates
  challan_document_id INTEGER REFERENCES source_document(id)
);

CREATE VIEW account_balance AS
SELECT a.id AS account_id,
       a.opening_balance_paise
       + COALESCE(SUM(CASE WHEN t.direction = 'credit' THEN t.amount_paise
                           ELSE -t.amount_paise END), 0) AS calculated_balance_paise
FROM bank_account a
LEFT JOIN bank_txn t
  ON t.account_id = a.id AND t.txn_date >= a.opening_balance_at
  AND t.status <> 'REVERSED'
GROUP BY a.id;

-- Planning
CREATE TABLE plan_run (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  created_at TEXT NOT NULL,
  triggered_by TEXT NOT NULL,           -- 'monday', 'event:<id>', 'what_if'
  inputs_sha256 TEXT NOT NULL,
  planner_version TEXT NOT NULL,
  opening_cash_paise INTEGER NOT NULL,
  lowest_balance_paise INTEGER NOT NULL,
  lowest_on TEXT NOT NULL,              -- lowest of the full schedule (Planning engine, step 4)
  valid INTEGER NOT NULL CHECK (valid IN (0,1)),
  is_current INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE plan_line (
  plan_run_id INTEGER NOT NULL REFERENCES plan_run(id),
  payable_id INTEGER NOT NULL REFERENCES payable(id),
  decision TEXT NOT NULL CHECK (decision IN ('PAY','WAIT','ESCALATE')),
  pay_on TEXT,
  reason TEXT NOT NULL,
  PRIMARY KEY (plan_run_id, payable_id)
);

CREATE TABLE plan_day (
  plan_run_id INTEGER NOT NULL REFERENCES plan_run(id),
  day TEXT NOT NULL,
  balance_paise INTEGER NOT NULL,
  PRIMARY KEY (plan_run_id, day)
);

CREATE TABLE shortfall_option (
  id INTEGER PRIMARY KEY,
  plan_run_id INTEGER NOT NULL REFERENCES plan_run(id),
  kind TEXT NOT NULL CHECK (kind IN
    ('early_receipt','split','delay_flexible','authorise_breach','ask_ca')),
  params_json TEXT NOT NULL,
  lowest_balance_paise INTEGER,
  meets_rule INTEGER NOT NULL CHECK (meets_rule IN (0,1)),
  chosen_by INTEGER REFERENCES app_user(id),
  chosen_at TEXT
);

-- Agent, owner questions, jobs, Gmail
CREATE TABLE agent_case (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  kind TEXT NOT NULL CHECK (kind IN
    ('unknown_txn','drift','failed_payment','ambiguous_match')),
  subject_ref TEXT NOT NULL,            -- e.g. 'bank_txn:41'
  stake_paise INTEGER NOT NULL,
  thinking TEXT NOT NULL CHECK (thinking IN ('medium','high')),
  steps INTEGER NOT NULL DEFAULT 0,
  validation_failures INTEGER NOT NULL DEFAULT 0,
  case_file_md TEXT NOT NULL,
  escalation_rule TEXT,
  status TEXT NOT NULL
    CHECK (status IN ('OPEN','RESOLVED','ASK_OWNER','CLOSED_BY_OWNER')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE owner_question (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  case_id INTEGER REFERENCES agent_case(id),
  kind TEXT NOT NULL CHECK (kind IN
    ('confirm_record','unlock_pdf','explain_txn','confirm_balance','choose_option',
     'approve_bank_change','reconnect_gmail','ca_reminder')),
  body_text TEXT NOT NULL,              -- shown as plain text
  choices_json TEXT,
  answer_json TEXT,
  answered_by INTEGER REFERENCES app_user(id),
  answered_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('OPEN','ANSWERED','EXPIRED'))
);

CREATE TABLE job (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                   -- one of the job kinds in "Jobs and the document pipeline"
  payload_json TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','dead')),
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  run_after TEXT NOT NULL,
  locked_at TEXT,
  last_error TEXT
);

CREATE TABLE gmail_connection (
  id INTEGER PRIMARY KEY CHECK (id = 1),    -- one mailbox per installation
  email_address TEXT NOT NULL,
  scope TEXT NOT NULL
    CHECK (scope = 'https://www.googleapis.com/auth/gmail.readonly'),
  refresh_token_enc BLOB,                   -- Fernet-encrypted; NULL after disconnect; access tokens are never stored
  status TEXT NOT NULL CHECK (status IN ('CONNECTED','DISCONNECTED')),
  connected_at TEXT NOT NULL,
  disconnected_at TEXT,
  last_error TEXT
);

CREATE TABLE sync_state (
  source TEXT PRIMARY KEY,              -- 'gmail' or 'eml_folder'
  last_synced_at TEXT
);

-- Audit trail
CREATE TABLE event (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  occurred_at TEXT NOT NULL,
  actor TEXT NOT NULL,                  -- 'owner:3', 'planner', 'reconciler', 'pipeline'
  event_type TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  before_json TEXT,
  after_json TEXT,
  reason TEXT,
  source_ref TEXT,
  trace_run_id TEXT
);
CREATE TRIGGER event_no_update BEFORE UPDATE ON event
  BEGIN SELECT RAISE(ABORT, 'event is append-only'); END;
CREATE TRIGGER event_no_delete BEFORE DELETE ON event
  BEGIN SELECT RAISE(ABORT, 'event is append-only'); END;
```

A split payable keeps its row with status SPLIT and gains two child rows. Logins use a signed session cookie (itsdangerous), so there is no sessions table; passwords are hashed with Argon2.

## Ledger writer

Every state change goes through one function, `transition(entity, to_state, actor, reason, source_ref)`. It checks the move against the table below, bumps `version`, and writes the event row in the same database transaction. Any actor starting with `agent:` is refused for every transition, which is what makes "the AI cannot approve or mark paid" true in code.

| From | To | Allowed actor | Trigger |
| --- | --- | --- | --- |
| DRAFT | CONFIRMED | owner | Owner confirms an extracted bill |
| CONFIRMED | PLANNED | planner | Plan gives the bill a PAY date |
| PLANNED | CONFIRMED | planner | A re-plan changes PAY to WAIT |
| REOPENED | PLANNED | planner | Re-plan after a failure or reversal |
| PLANNED | PAYMENT_EXPECTED | owner | Owner approves the plan |
| PAYMENT_EXPECTED | PAID | reconciler, owner | Debit matched, or owner marks paid |
| PAYMENT_EXPECTED | REVIEW | reconciler | Match is ambiguous |
| PAYMENT_EXPECTED | REOPENED | reconciler | Failure or return email |
| REVIEW | PAID | owner | Owner says it was paid |
| REVIEW | REOPENED | owner | Owner says it failed |
| PAID | REOPENED | reconciler | Reversal or return after payment |
| CONFIRMED, PLANNED | SPLIT | owner | Owner chooses the split option |

Owner actions arrive with the plan or record `version` the owner saw. If the version has moved on, the write is refused and the page shows the new figures.

## HTTP routes

Pages return full HTML; actions are HTMX POSTs that return the HTML fragment to swap in. The role is checked by a FastAPI dependency on every route, and every POST carries a CSRF token.

| Method | Path | Role | What it does |
| --- | --- | --- | --- |
| GET, POST | /login, /logout | anyone | Session cookie (HttpOnly, SameSite=Lax) |
| GET | / | owner | This week: payments by day, lowest balance, safety amount |
| GET | /attention | owner | Needs attention: questions, bills to confirm, mismatches, options |
| GET | /add | owner, helper | Upload or type a bill, invoice or voice note; a helper also sees the status of his own submissions, and nothing else |
| GET | /accounts | owner | Balances and drift status per account, and the Gmail connection |
| GET, POST | /settings | owner | Safety amount, payment days, horizon, priorities, escalation amount, language; every change is recorded as an event |
| POST | /uploads | owner, helper | Stores the file encrypted, creates a source document, queues processing |
| POST | /entries | owner, helper | Typed entry, saved as a candidate |
| POST | /candidates/{id}/confirm | owner | Accepts an extracted record with any edits; DRAFT to CONFIRMED |
| POST | /candidates/{id}/reject | owner | Rejects an extracted record |
| POST | /plans/{run_id}/approve | owner | Approves PAY lines for the next payment day; refused if the plan is not current |
| POST | /payables/{id}/mark-paid | owner | PAYMENT_EXPECTED or REVIEW to PAID |
| POST | /options/{id}/choose | owner | Records the chosen shortfall option and re-plans |
| POST | /questions/{id}/answer | owner | Answers an agent question and closes or resumes its case |
| POST | /accounts/{id}/confirm-balance | owner | Owner states the real balance; writes an adjustment transaction |
| POST | /documents/{id}/unlock | owner | Password used in memory to unlock a statement, never stored or logged |
| POST | /parties/{id}/bank-change | owner | Approves or rejects a vendor bank detail change |
| GET | /api/plan/current | owner | Current plan as JSON, for evals and debugging |
| POST | /api/what-if | owner | Runs the planner on a changed snapshot; writes nothing |
| GET | /api/health | anyone | Database, worker heartbeat, queue depth |
| GET | /gmail/connect | owner | Starts Google consent for read-only Gmail access |
| GET | /gmail/callback | owner | Checks state and scope, stores the encrypted refresh token, queues a poll |
| POST | /gmail/disconnect | owner | Revokes the token with Google and deletes it |

## Gmail ingestion

Gmail and the test inbox implement the same three-method interface. The rest of the system, including the agent's search tool, never knows which one it is talking to.

```python
class MailSource(Protocol):
    def list_new(self, since: date, senders: list[str]) -> list[MessageRef]: ...
    def fetch(self, ref: MessageRef) -> RawMessage: ...          # RFC 2822 bytes + attachments
    def search(self, query: str, limit: int = 20) -> list[MessageSummary]: ...
```

**GmailSource**

- OAuth with the `gmail.readonly` scope only; the refresh token is encrypted with a Fernet key from the environment
- `list_new` calls `messages.list` with a query like `from:(alerts@bank.example OR billing@vendor.example) after:2026/10/11`
- Senders come from `bank_account.alert_senders_json` plus vendor and customer addresses
- The `after:` date is the last sync date minus one day, so nothing is missed at the boundary
- `fetch` calls `messages.get` with the raw format; the message is stored encrypted as a source document
- The Gmail message ID is the document's `external_ref`, so a message seen twice is skipped by the unique key

**EmlFolderSource**

- Reads `.eml` files from `TEST_INBOX_PATH` (default `fixtures/test_inbox/`) or an eval scenario folder
- Uses each file's Date header and the injected Clock, so a scenario can release emails day by day
- `search` runs a simple match over sender, subject and body, so the agent's tool works in tests

**The poll job.** APScheduler queues `poll_mail` every 5 minutes. It lists new messages, inserts a source document for each, and queues one `process_document` job per document with the document ID as its idempotency key. A crash part-way through is safe: the next poll finds the same messages and the unique keys skip the ones already stored.

**Connecting Gmail.** OAuth 2.0 runs once, when the owner connects; after that the backend calls the Gmail API with tokens it already holds. The AI agent never sees a token and reaches Gmail only through the `search_gmail` tool.

One-time setup in Google Cloud, done by the developers:

1. Create a project and enable the Gmail API.
2. Configure the OAuth consent screen: External user type, Testing status, only the `gmail.readonly` scope, and the demo account added as a test user. Use Internal instead if that account is on Google Workspace.
3. Create a web-application OAuth client whose redirect URI equals `GOOGLE_REDIRECT_URI`, and put its ID and secret in `.env`.

Connect flow, started by the owner from Accounts:

1. `GET /gmail/connect` generates a random `state`, keeps it in the session, and redirects to Google with scope `gmail.readonly`, `access_type=offline` and `prompt=consent`, so a refresh token is always returned.
2. The owner signs in to Google and approves read-only access.
3. `GET /gmail/callback` checks `state`, exchanges the code for tokens, and refuses the connection if the granted scope is anything other than `gmail.readonly`.
4. The refresh token is Fernet-encrypted into `gmail_connection` with status CONNECTED, a GMAIL_CONNECTED event is written, and `poll_mail` is queued.

Every poll builds credentials from the stored refresh token. google-auth refreshes the access token in memory only; access tokens are never written anywhere.

**When Google refuses the token.** Google returns `invalid_grant` when a Testing-mode token reaches 7 days, after a password change, or after the owner revokes access. `poll_mail` then:

1. Sets `gmail_connection.status` to DISCONNECTED, stores `last_error`, and writes a GMAIL_DISCONNECTED event
2. Opens a `reconnect_gmail` owner question and queues `send_alert`
3. Stops polling until the owner reconnects; `search_gmail` returns "Gmail disconnected" to the agent

The planner keeps running on existing data. Reconnecting repeats the connect flow, and polling resumes one day before the last sync.

**Disconnecting.** `POST /gmail/disconnect` revokes the token with Google, sets `refresh_token_enc` to NULL, sets status DISCONNECTED, and writes an event.

## Jobs and the document pipeline

All background work is a row in the job table, so nothing is lost if the worker stops. The names in the Job column are the exact values of `job.kind`. The worker claims one job at a time with `UPDATE … RETURNING`, retries with backoff, and marks a job dead after 5 attempts.

| Job | Queued by | What it does |
| --- | --- | --- |
| poll_mail | Scheduler, every 5 minutes | Lists new messages and stores source documents |
| process_document | poll_mail, uploads | Runs the pipeline below for one document |
| reconcile_txn | Pipeline, after a new transaction | Matches a debit or credit to the plan |
| reconcile_failure | Pipeline, after a failure or return email | Reopens the matched bill |
| drift_check | Pipeline, after a reported balance | Compares reported and calculated balances |
| run_case | Reconciler and drift check | Runs the exception agent on one case |
| replan | Any ledger change | Rebuilds the plan; a queued replan absorbs later requests |
| monday_plan | Scheduler, Monday 07:00 | Full weekly plan plus the owner's summary |
| explain_plan | replan, monday_plan | Writes the plain-text summary of what changed |
| send_alert | Anything the owner must see | Sends a fixed-template email |

**The pipeline for one document**

1. Sort with Gemini at low thinking. Irrelevant documents are marked and stop here.
2. Unlock if needed. An encrypted PDF is marked LOCKED and the owner is asked for its password (`unlock_pdf`); the job resumes after he answers.
3. Extract with Gemini at medium thinking, using a JSON schema generated from the Pydantic model. Voice notes return the transcript and the record in one call.
4. Validate with every rule check. A failure triggers one more extraction with the failed checks attached.
5. Escalate a second failure: extract once more at high thinking, then ask the owner to fill the fields that still fail.
6. Route the valid candidate:
    - Bank alert or statement row: written to the ledger by the pipeline, then reconcile_txn is queued
    - Statement: missing rows added, existing rows confirmed, reported balance stored, drift_check queued
    - Bill, sales invoice or challan: shown to the owner to confirm (`confirm_record`), then written and re-planned
    - Failure or return email: reconcile_failure queued
    - Vendor bank details that differ from the stored ones: vendor marked change_pending and the owner asked (`approve_bank_change`); never updated automatically

## Planning engine

The planner is a pure function: the same snapshot always gives the same plan, byte for byte. It reads no clock, no database and no network; the job that calls it builds the snapshot and stores the result.

```python
@dataclass(frozen=True)
class PlanSnapshot:
    today: date
    horizon_days: int
    payment_days: frozenset[int]          # 0 = Monday
    safety_paise: int
    accounts: tuple[AccountCash, ...]     # calculated, reported, drift flag
    payables: tuple[PayableIn, ...]       # CONFIRMED, PLANNED, REOPENED, PAYMENT_EXPECTED
    inflows: tuple[InflowIn, ...]         # COMMITTED receivables dated inside the horizon
    commitments: tuple[CommitmentIn, ...] # fixed outflows entered by the owner

def plan(s: PlanSnapshot) -> PlanResult: ...
def options(s: PlanSnapshot, r: PlanResult) -> list[OptionResult]: ...
```

**Algorithm**

1. Opening cash is the sum of account balances, using the lower of calculated and reported for any account with unresolved drift.
2. The base curve gives each day's balance from opening cash, counted inflows, commitments, and payments already in PAYMENT_EXPECTED.
3. Each remaining bill gets a target day: the latest payment day on or before its due date, or its discount date if that saves money. An overdue bill targets the next payment day; a bill due after the horizon gets WAIT.
4. The full schedule subtracts every bill on its target day. Its lowest balance is the figure the owner sees and every option is compared against.
5. Bills are then placed one at a time: statutory, critical, normal, flexible, and by due date then ID within a level.
6. A bill gets PAY if every day from its target onward stays at or above the safety amount. Statutory bills always get PAY, and a breach they cause makes the plan invalid rather than delaying them.
7. Any other bill that would breach gets ESCALATE, with the breach day and the gap in its reason. The plan is valid when nothing is escalated.

**Shortfall options.** Each option is the same `plan()` run on a changed snapshot, so its numbers come from the same code.

| Option | Generated when | How it is computed |
| --- | --- | --- |
| early_receipt | A COMMITTED or EXPECTED receivable is dated after the breach | Moved to the last weekday (Monday to Friday) before the payment day preceding the breach |
| split | A bill is escalated | Pay now = amount minus the gap; the rest becomes a child bill after the horizon |
| delay_flexible | A flexible bill with grace days is in the horizon | Moved to the latest payment day within its grace days |
| authorise_breach | Always, when the plan is invalid | No change; shows the gap below the safety amount |
| ask_ca | The breach remains even with every non-statutory bill removed | No numbers; adds a ca_reminder item for the owner |

With the worked example these rules give Fri 16 Oct for Nandi and ₹53,000 for the Prime Chem split, matching Part 1.

**Tests.** The worked example is a golden test that must reproduce ₹1,83,000, the three options, ₹3,83,000, and every daily balance in Part 1's golden table. Hypothesis checks the Part 1 invariants on random snapshots, plus one more: running `plan()` twice on the same snapshot gives identical output.

**Explaining a change.** `diff.py` lists what changed between two plan runs. Gemini writes the plain-text summary from that list, and a check rejects any summary containing an amount or date not in the list; the fallback is a fixed template.

## Reconciliation and drift

Matching is plain code with exact amounts in paise. The agent only gets the cases this code cannot settle.

**A new debit**

1. Find PAYMENT_EXPECTED bills with the same amount and a planned date within 3 days of the debit.
2. Compare names after normalising: upper case, punctuation removed, and words like PVT, LTD and M/S dropped. A name matches when it equals, or contains, the vendor's name or one of its aliases.
3. Exactly one bill with a matching name: the debit is MATCHED and the bill becomes PAID.
4. One bill without a name match, or several bills: the bill moves to REVIEW and an ambiguous_match case opens.
5. No bill at all: the debit stays UNMATCHED and an unknown_txn case opens.

A name from a bank alert is added to a vendor's aliases only after the owner confirms the match. Otherwise a crafted alert could teach the matcher a false name.

**A new credit** follows the same steps against open receivables. A match marks the receivable CONFIRMED; a different amount opens a case.

**Failures and reversals.** A failure or return email is matched to a PAID or PAYMENT_EXPECTED bill by amount and reference. The bill becomes REOPENED, any original debit is marked REVERSED, and a replan is queued. A failure email that matches no bill opens a failed_payment case.

**Drift check**

1. A reported balance comes from an alert's available balance or a statement's closing balance.
2. The calculated balance at that moment counts every transaction dated on or before it.
3. Same-day transactions can arrive out of order, so a mismatch from an alert is checked again at 23:00 before anything else happens. A statement mismatch is acted on at once.
4. A mismatch that remains sets the account to CHECKING and opens a drift case for the agent.
5. If the agent's findings close the gap, the account returns to OK. Otherwise it becomes ASK_OWNER and the owner is asked for the real balance (`confirm_balance`).
6. The owner's answer writes an ADJUSTMENT transaction for the difference, with the owner as actor, and the account returns to OK.

While an account is not OK, every planner snapshot uses the lower of its two balances.

## Agent loop

Each step is one Gemini call with the case file, not a growing chat history, so a run can stop and resume at any step. Code opens the case, checks every tool call, counts the limits, and applies the result; the model only chooses the next step.

```mermaid
flowchart TD
    OPEN[Case opens<br/>code fills in the facts;<br/>over escalation amount: high] --> STEP[Gemini step<br/>reads the case file;<br/>returns a tool or an answer]
    STEP --> FINAL{Final answer?}
    FINAL -- yes --> APPLY[Apply the answer<br/>evidence checked by code;<br/>owner approves what he must]
    FINAL -- no --> TOOL[Run the tool<br/>allow-list, schema check;<br/>result into the case file]
    TOOL --> LIMITS{Limits hit?<br/>6 steps, or 2 failed checks}
    LIMITS -- no --> STEP
    LIMITS -- yes --> MEDIUM{At medium?}
    MEDIUM -- yes --> RERUN[Rerun at high<br/>steps reset to zero] --> STEP
    MEDIUM -- no --> ASK[Ask the owner<br/>question shown as plain text]
```

```python
def run_case(case_id: int) -> None:
    case = cases.load(case_id)
    while case.steps < config.max_steps:                 # 6
        step = ai.call(
            job="exception",
            thinking=case.thinking,                       # medium or high
            system=prompts.load("exception_agent"),
            context=case.case_file_md,
            schema=AgentStep,                             # notes + one tool call, or a final answer
        )
        trace.step(case, step)
        case.add_notes(step.notes)
        if step.final:
            return apply_final(case, step.final)          # code checks the evidence first
        tool = TOOLS.get(step.tool.name)
        if tool is None:
            case.add_notes(f"refused unknown tool {step.tool.name}")
        else:
            args = tool.args_model.model_validate(step.tool.args)
            case.add_result(tool.name, tool.run(case, args))  # summary in the file, full result in the trace
        case.steps += 1
        if case.validation_failures >= 2:
            break
        cases.save(case)
    escalate_or_ask(case)   # medium -> rerun at high; high -> ask the owner
```

**The case file** has five parts: goal, facts filled in by code when the case opens, findings with source references, unknowns, and notes. Each tool result is cut to 20 lines in the file; the full result stays in the trace.

**Tools**

| Tool | Arguments | Returns | Limits |
| --- | --- | --- | --- |
| search_gmail | query, limit up to 20 | Sender, date, subject, snippet, message ID | Read-only; this business's mailbox only |
| get_ledger | table, account, date range, amount, party | Matching rows | Read-only connection; at most 50 rows |
| run_planner | Optional what-if changes | Lowest balance, breach day, plan lines | Writes nothing |
| add_candidate | Record type, fields, source message ID | Candidate ID and rule-check results | Message ID must come from this case's searches; never writes the ledger |
| ask_owner | Question up to 300 characters, up to 4 choices | Question ID; ends the run | Shown as plain text; one open question per case |

**Escalation (`escalation.py`)**

- When the case opens: a stake above the business's escalation amount starts it at high thinking
- During a run: 6 steps, or 2 candidates failing rule checks, ends the run
- After a medium run ends this way: the case reruns at high with its step count reset
- After a high run ends this way: the case goes to the owner

**Applying a final answer.** RESOLVED is accepted only if every cited message ID came from this case's own searches and every candidate it relies on passed the rule checks. Anything that needs the owner's approval still goes to him, however confident the agent is.

## Tracing, configuration and security

**Tracing.** Every job run gets a run ID of the job ID plus the attempt number. `ai.call`, every tool call and every rule check write one JSON line to `traces/<date>/<run_id>.jsonl`, with the trace fields listed in Part 1. Event rows carry the same run ID, so an audit entry links to the trace that caused it. `python -m app.trace.view <run_id>` prints a run as readable steps.

**Configuration.** One `config.yaml`, loaded and checked by Pydantic at start-up. Changing anything under `model` or `prompts` runs the scenario suite in CI before merge.

```yaml
model:
  id: gemini-3.8-flash
  thinking: {sort: low, extract: medium, voice: medium, exception: medium, explain: low}
prompts:
  version: 2026-10-02.1
escalation:
  max_steps: 6
  default_stake_paise: 5000000  # ₹50,000; the owner can change it in Settings
  max_validation_failures: 2
matching:
  window_days: 3
mail:
  poll_minutes: 5
alerts:
  min_minutes_between_emails: 30
```

**Security in code**

- Secrets (Gemini key, Google client secret, SMTP password, Fernet key, session secret) come from environment variables; `.env` is git-ignored
- Stored emails, uploads and the Gmail refresh token are encrypted with Fernet before they touch disk
- The tracer redacts any field named password, token or key, and the unlock route never passes the password to the tracer
- The agent's ledger tool uses a SQLite connection opened read-only (`mode=ro`), so it cannot write even if the code is wrong
- Every query filters by the logged-in user's business ID through one repository layer
- Templates escape everything, and AI text is rendered as plain text with no Markdown or HTML
- Owner alert emails use fixed templates, a fixed recipient from the database, and an SMTP account separate from Gmail

## MVP build sequence

Build the deterministic core and the test inbox first, and connect live Gmail last. Every phase until then runs on fixtures, so it is reproducible and testable from day one. Person A owns ingestion and AI; person B owns ledger, planner and web.

| Phase | Build | Who | Done when |
| --- | --- | --- | --- |
| 0. Skeleton | Repo layout, Makefile, .env.example, config, schema and migrations, seed data, Clock, tracer, job table, CI with pytest and import-linter | Both | make setup, make db, make seed and make run work on a clean machine, and CI is green |
| 1. Ledger core | Domain models, ledger writer, transition table, event triggers | B | A transition by an agent actor is refused; updating an event row fails |
| 2. Planner | plan(), options(), diff(), snapshot builder | B | The worked example golden test and the Hypothesis invariants pass |
| 3. Alert ingestion | MailSource, test inbox, ai.client, sort, extract and validate for bank alerts | A | A sample bank alert .eml becomes a transaction, with a readable trace |
| 4. Reconciliation | Matching, failures, reversals, drift check | B | Approved payment plus debit alert gives PAID; a return email gives REOPENED; a missing alert gives CHECKING |
| 5. Web app | Login, This week, Needs attention, confirm, approve, mark paid, options | B | The owner plays through the worked example in the browser |
| 6. Bills and uploads | Invoices by email, photos, PDF unlock, voice notes, all rule checks | A | The photo, PDF, voice and duplicate scenarios pass |
| 7. Exception agent | Loop, tools, case file, escalation | A | Unknown debit and drift scenarios resolve or reach the owner within the limits |
| 8. Live connections | Gmail OAuth, GmailSource, SMTP alerts | A | Synthetic emails sent to a test Gmail account flow end to end, and revoking access produces a Reconnect Gmail item |
| 9. Evidence | Scenario runs, harness comparison, attack, two traces, demo video | Both | The eval report and threat model are written and the demo is recorded |

Phases 1 and 2 run alongside phase 3. The first joint checkpoint is the end of phase 4: a test-inbox debit alert reconciles against a payment approved through the planner.

## Open questions (build)

None. All implementation questions were settled on 2 Oct 2026 and are recorded in Part 1's decisions log. The one remaining product question, the escalation starting values, is in Part 1 and does not block the build.
