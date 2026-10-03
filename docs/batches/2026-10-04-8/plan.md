# Batch 8: plan (CHG-029 first bank details; CHG-028 statutory debits; CHG-030 missing due dates; CHG-031 drift recovery)

**Goal:** close the two gaps that batch 7's review and runs found (D26, D27), and fix the two failures that the first live run found on the real model. The live run is the BEFORE (`docs/evals/2026-10-04-live-pilot/`). A live rerun of scenarios 04 and 07 after the fixes is the AFTER, kept beside it.

**Branch:** `batch-8`, cut from main at fc6d738. Order: CHG-029, CHG-028, CHG-030, CHG-031 (PO).

**Router:** all four are `planned`. Each sits in one or two modules and shows on one screen or with one command. None migrates data or consumes a contract I didn't write: the statutory keywords are our own config. CHG-029 is a security fix, so its plan names its tests up front.

**Standing policies:**
- No live Gemini or SMTP in the build. The AFTER rerun of 04 and 07 is PO-authorised, at about 20 calls.
- Never read .env.
- `make test` through yt_gate.py is the gate of record.
- The review is split by subsystem, and only fix commits are re-reviewed.
- Main is pushed only after the PO accepts.

---

## CHG-029: a vendor's first bank details need the owner's approval (D26, planned)

**Rule (D26):** bank details read from any document, for a vendor with none on record, are a material banking change, exactly like a change. They are recorded as `change_pending` with an approve_bank_change question, which is an owner decision separate from confirming the bill. Until the owner approves, the bill shows the D20 warning, and approving its payment needs the tick.

**Where:**
- `app/ingest/pipeline.py::_check_bank_details` stops skipping a vendor with `bank_status = 'none'`.
- `app/ledger/writer.py::flag_bank_change` treats "none on record" as a change. Today `differs()` is False when nothing is on record, so a first proposal must be flagged explicitly (status none → change_pending).
- The question text says "no bank details on record" instead of "(on record: )" (`app/validate/bank.py::change_question`).
- `app/web/actions.py::_create_record` flags a document's first details, not recording them. `writer.record_bank_details` goes, with its one caller.
- Typed entries carry no bank fields, so D26's "owner-typed details may be verified" has no path today. That is noted, not built.
- Approve stores the details as verified, unchanged. Reject leaves the vendor with none, also unchanged: `decide_bank_change` already returns to `none` when nothing was on record.
- README and threat model: the CHG-029 known limit comes out. The walkthrough and the demo script gain the owner approving Ashirwad's first details on Tuesday.

**Tests (named up front):**
- a fake first invoice (fixture 09's AP/2610/140, confirmed before any real one) leaves the vendor `change_pending` with no details stored, and only an explicit approve_bank_change stores them;
- the bill shows the D20 warning, and approving its payment is refused without the tick;
- reject leaves the vendor with none, and the next document is flagged again;
- the helper can't approve (owner only, unchanged);
- workflow B gains a check: the fake first invoice can't set an account until the owner approves.

**Expected knock-on:** tests, scenarios and workflow steps that relied on first details being recorded silently gain an owner approval step. Each one is listed in the commit.

## CHG-028: statutory debits match by payee keywords (D27, planned)

**Rule (D27):** a statutory payable has no party, so `match_debit` matches it by a config list of payee keywords per tax_type. These keywords act as the statutory "aliases". Keyword, plus the same amount, plus the same window (`matching.window_days`, 3) gives MATCHED as reconciler, as for a named bill. More than one candidate goes to REVIEW, as now. The owner's link stays as the fallback.

**Where:**
- `config.yaml` `matching.statutory_payees`:
  - PF: [EPFO]
  - ESI: [ESIC]
  - GST: [GST, CBIC, GSTN]
  - TDS and ADVANCE_TAX: [CBDT, ITD, TIN-NSDL, OLTAS]

  Pydantic checks that the keys are the tax types.
- `app/ledger/reconcile.py::match_debit`: a candidate bill's payee names are its party's names. For a bill with no party, they are the keywords of the tax types whose `tax_obligation` points at it. A keyword must match a whole word of the normalised counterparty, so "GST" doesn't match inside another word.
- The reconcile job passes the config down. Reconcile already takes window_days, and the planner stays pure.

**Tests:**
- an "EPFO ESIC CHALLAN" debit of the PF/ESI amount, in the window → PAID by the reconciler;
- a GST challan → the GST bill;
- a keyword debit with two statutory bills of the same amount → REVIEW;
- a debit with no keyword stays a case;
- a keyword alone, without the amount, matches nothing.

**Workflow A:** step 11 expects PF/ESI PAID with no owner action. Step 12 keeps the owner's link as its own check, on a challan debit whose payee names no keyword (a fixture alert, with its source noted).

## CHG-030: a missing due date reaches the owner flagged, never as a broken value (planned)

**Found by the live pilot, scenario 04.** The speaker said "5 November" with no year, and the model returned no due date, as its prompt says. The voice checks then mark `dates` as not applicable and route the bill as "all checks passed", so the owner's form gets an empty required field with no flag. The scripted owner confirmed it and the form refused it ("due_date: Enter a date."), which the eval scored as a crash.

**Where:**
- **(a) Product.** A bill read from any document (voice, invoice or photo) with no due date fails a `dates` check that names the field: "no due date was given: fill it in".
  - The entry goes to the owner as AWAITING_OWNER with that field flagged, so it is never shown as passing.
  - Asking the model again can't supply a date that wasn't said, so this check stops the retry ladder, like `confidence`.
  - The voice prompt says to leave the date empty when the speaker gave no full date, and never to guess a year.
  - This is fixed generally, not for this clip.
- **(b) Eval scoring.** When the form refuses a scenario's scripted owner action because of an extracted value (`FieldErrors`), the run fails at component `extract` with the form's message, not as a crash. Real exceptions keep the crash class.
- **Scenario 04.** The scripted owner fills the flagged field, as a real owner would (`confirm_waiting` with `fill: {due_date: ...}`, used only for fields the entry flags). A check asserts that the field was flagged.

**Tests:**
- a voice extract with no due date → AWAITING_OWNER, with `dates` failed and named, after one attempt;
- the same for an invoice;
- a form refusal in a scenario → component extract;
- a real exception → crash.

## CHG-031: the agent can finish a drift case when the evidence is in the mailbox (planned)

**Found by the live pilot, scenario 07, and diagnosed from the kept trace (job 11):**
1. The agent found the missed alert (`11-debit-shree-transport-missed.eml`) and named it as the ₹20,000 gap.
2. Its add_candidate `fields` used names of its own (`account`, `amount`, `date`, `counterparty`). Neither the prompt nor the tool says which fields a bank_alert record has.
3. The tool replied "9 field error(s): Field required", naming none.
4. The agent then gave a RESOLVED answer relying on no candidate. Code accepted it, the gap stayed open, and the account went to ASK_OWNER.
5. When the run ended, the message was handed on to the pipeline. The pipeline wrote the debit with the document as its source, not the case (D21).
6. Code then opened a new unknown_txn case for that debit, and the agent asked the owner about it.

**Where (harness only; nothing hard-codes the answer):**
- **Prompt:**
  - add_candidate's `fields` are listed per record type, generated from `BankAlertExtract` and `InvoiceExtract` so they can't drift; a test checks that the prompt names every field;
  - the agent is told to read a refusal, fix the call and try again within its limits;
  - for a drift case, the agent is told to search by the account's alert sender and the case's date window.
- **Tool replies:** a schema failure names every missing and unexpected field, and the expected names.
- **Code:** a drift case's RESOLVED answer that relies on no VALID bank_alert candidate is refused, with a message saying a missing debit must be proposed with add_candidate. The run goes on within its limits, so the agent can fix its call; an empty resolution no longer sends the case to the owner.
- **Case facts:** a drift case's facts name the account's alert sender, the gap amount and the date window (from the last statement or balance date to the recheck), where they aren't there already.
- **Provenance (D21):** a message the agent stored and handed on to the pipeline carries the case. The process_document payload names the case, and the pipeline writes the transaction with source `agent:case:<id> via source_document:<id>`. If the agent found it, the source says so.
- Asking the owner when the evidence isn't there stays allowed and safe.

**Tests:**
- a schema refusal names the missing fields;
- the prompt lists every field of both schemas;
- a drift RESOLVED with no candidate is refused, and the run continues;
- a handed-on message's transaction carries `agent:case:`;
- a fixture replay of the live trace's mistake (wrong field names, then the right ones) resolves the case at medium.

---

## AFTER (PO-authorised, about 20 calls)

When the four changes are in, I run scenarios 04 and 07 live once with traces kept. Their report is committed beside the pilot's, as `docs/evals/<date>-live-after-batch-8/`. Whatever it shows is reported as is. Phase 2 (11×5, the ablation per harness, workflow A and B, the degraded-prompt variant) waits for the PO to accept this batch.
