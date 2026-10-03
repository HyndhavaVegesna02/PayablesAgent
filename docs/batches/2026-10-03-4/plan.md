# Batch 4 — Plan

**Covers:**
- **CHG-022:** the owner says which bill a debit paid. Lane `planned`. Clears KL-1.
- **CHG-021:** the planner honours the owner's authorise_breach and delay_flexible choices. Lane `planned`.
- **CHG-023:** a chosen early_receipt that is still pending shows as chosen. Lane `direct`. Folded in because it touches the same option paths as CHG-021.

**Not in this batch: CHG-007.** I counted about 12 steps:
1. the validators package;
2. multimodal AI input (image, PDF, audio), which changes the ai.client contract;
3. invoices by email and photo;
4. PDF unlock;
5. statements;
6. voice;
7. vendor bank change;
8. cross-source duplicates;
9. D11 MISSING tax;
10. upload processing;
11. fixtures and fixture-AI replies for each scenario;
12. the Phase 6 exit test.

That is past the ~8-step line the PO set, so CHG-007 becomes **batch 5 on its own**. Its plan will carry every PO requirement from the batch 4 brief:
- the pure app/validate subpackage, with a README and an import-linter contract;
- the GSTIN mod-36 check, with fictional but valid GSTINs and a note of their source;
- the PDF password never reaching the trace, the DB, the logs or job.last_error;
- voice "dedh lakh" giving ₹1,50,000 through code, with no stored number coming from the model;
- the bank-change flow: change_pending, approve_bank_change, owner-only approval, and an injected-email test;
- an invoice by email and by photo becoming one payable;
- one copy of the fixture replies.

I may slice CHG-007 there.

**Branch:** `batch-4`, cut from `main` at 24c747e or later. The changes run in order: CHG-022, then CHG-021, then CHG-023. CHG-021 and CHG-023 share files.

**Standing policies:**
- No live Gemini; this batch has no AI change at all.
- Never read .env.
- Gate of record: `make test` through yt_gate.py.
- Review split by subsystem; re-review only the fix commits.

**Router:**
- **CHG-022 → `planned`.** It extends a contract I didn't write: the payable and bank_txn state tables, which are the TDD's. It needs the enumeration below.
- **CHG-021 → `planned`.** A new table (a migration) and a new planner input. The planner stays pure.
- **CHG-023 → `direct`.** A display change in one module, shown on one screen.

---

## CHG-022: the owner says which bill a debit paid (planned)

**Where the owner acts (Q1).** When the reconciler opens an `ambiguous_match` or `unknown_txn` case for a debit, it also raises an `explain_txn` owner question, with `choices_json = {"case_id": …, "bank_txn_id": …}`. The owner answers on Needs attention through the existing POST /questions/{id}/answer, which is the TDD route "Answers an agent question and closes or resumes its case". There is no new route. When the agent arrives (CHG-008), it can take over raising these questions, after its own steps.

**The answer form** shows the debit's facts: date, amount, payee as written, reference. It then offers:
- **"This paid …"**, with a list of candidate bills. These are the business's open bills a debit could pay: PAID with no linked debit, PAYMENT_EXPECTED and REVIEW. They are sorted by how close their amount is to the debit's, then by planned date, and each shows its amount difference.
- **"Add '<payee as written>' as a name for <vendor>"**, a checkbox shown only when the name doesn't match. It is unchecked by default (Q3).
- **"Not a bill payment"**: the case is recorded as explained, and the debit stays as it is.

**What a link does,** in one transaction:
1. **The debit:** UNMATCHED → MATCHED, with the owner as actor. This is a new row in the bank_txn table (Q2).
2. **The bill:**
   - If it is PAID with no linked debit: `link_payment`, now allowed to the owner as well as the reconciler.
   - If it is PAYMENT_EXPECTED or REVIEW: → PAID with `matched_txn_id`. The owner already has these moves.
3. **An amount difference** (for example, TDS) is allowed. It is written into the event's reason as "debit ₹1,62,000 for a ₹1,80,000 bill: difference ₹18,000". The bill stays PAID at its own amount.
4. **Other REVIEW bills held for this debit** go REVIEW → PAYMENT_EXPECTED as the owner. This is a new row in the payable table, meaning "not this one; still expected" (Q4). It also clears batch 3's "REVIEW twins" minor.
5. **The alias**, if ticked, is added to the vendor's `aliases_json` through a new writer function, `add_party_alias`. It is owner only and writes a PARTY_ALIAS_ADDED event. The party table isn't guarded, but it is evented like every owner action.
6. **The case** becomes CLOSED_BY_OWNER and the question ANSWERED.
7. **The inline replan** runs.

**Contracts consumed:**

| Input | Units / shape | Empty | Absent | Failure | Cite |
|---|---|---|---|---|---|
| bank_txn state table | UNMATCHED → MATCHED: reconciler today | — | — | A transition the table refuses → 409, nothing written | app/domain/states.py, TDD "Payment states" |
| payable state table | REVIEW → PAYMENT_EXPECTED: no row today | — | — | as above | states.py |
| `agent_case.subject_ref` | `bank_txn:<id>` | — | A case whose subject is not a txn → no explain_txn question | A txn outside the business → 404 | reconcile.open_case |
| `party.aliases_json` | JSON list of strings, matched by `name_matches` after normalising | `[]` | NULL → treated as `[]` | Invalid JSON → 409, nothing written | schema, reconcile._party_names |

**Steps:**
1. **States:** owner UNMATCHED → MATCHED on bank_txn, and owner REVIEW → PAYMENT_EXPECTED on payable.
   - **Writer:** `link_payment` allows the owner and takes an optional `difference_paise` for the reason text; `add_party_alias` is new.
   - **Tests:** the table and the writer.
2. **The reconciler raises the question:** open_case raises an explain_txn question for debit cases, one per case, with the dedup that open_case already has.
3. **actions.explain_debit:** link, not-a-bill, the alias, the twins, closing the case, and the replan. It runs from /questions/{id}/answer for explain_txn.
4. **Needs attention:** the explain_txn form and the candidate list, with plain text everywhere.
5. **Tests:**
   - KL-1 becomes cleared: the pinned test is rewritten so that the owner's link removes the double count;
   - TDS difference;
   - alias, after which the next debit from that payee name-matches;
   - twins;
   - not a bill;
   - another business's bill → 404;
   - helper → 403.
6. Gate.

**Acceptance criteria (CHG-022):**
- **AC1:** For a debit that didn't auto-match, the owner picks the bill on Needs attention. The debit becomes MATCHED and the bill PAID and linked, with owner:1 events, and the plan subtracts the money once. The KL-1 test now passes in its "cleared" form.
- **AC2:** An amount difference is linked, and the difference is recorded in the event's reason. The bill keeps its own amount.
- **AC3:** "Add as a name" is owner-only and off by default. With it ticked, the next debit with that payee name auto-matches. Without it, nothing about the vendor changes.
- **AC4:** The other REVIEW bills held for that debit return to PAYMENT_EXPECTED, and the case closes as CLOSED_BY_OWNER.
- **AC5:** "Not a bill payment" closes the case and leaves the debit UNMATCHED and counted.
- **AC6:** Every action goes through the writer, in one transaction with the replan. A refusal writes nothing.

## CHG-021: the planner honours the owner's overrides (planned)

**Storage (Q5):**
- **Table:** a migration adds `plan_override`:
  - id, business_id, payable_id;
  - kind (`authorise_breach` or `delay_flexible`);
  - shortfall_option_id;
  - created_by, created_at;
  - status (`ACTIVE` or `ENDED`), ended_at.
- **Writer:** `record_override` and `end_override`, owner only, with PLAN_OVERRIDE_RECORDED and PLAN_OVERRIDE_ENDED events.
- **Recording:** choosing `authorise_breach` records one override for each ESCALATE bill in the run it was chosen from (Q6). Choosing `delay_flexible` records one for its bill.

**How long an override lasts (Q7):**
- It ends by itself when its bill leaves the plan: PAID, SPLIT, or REOPENED for a new attempt. The writer ends it in the same transaction as the bill's move.
- It does not expire on Monday.
- The owner can undo it from Needs attention, through POST /options/{id}/choose with `undo=1`. That is the same route, so the route table is unchanged.

**The snapshot:** `build_snapshot` reads the ACTIVE overrides into a new field, `PlanSnapshot.overrides`, a tuple of OverrideIn(payable_id, kind). The planner reads nothing else, so it stays pure. With no overrides, the result is byte-identical to today's; the golden tests and a Hypothesis property check this.

**What the planner does with an override:**
- **authorise_breach:** the bill is placed on its normal target day, like a statutory bill. Its reason reads "Pay ₹1,20,000 on Thu 22 Oct: authorised by the owner although it takes the balance ₹67,000 below the safety amount." It is PAY, not ESCALATE.
  - `PlanResult` gains `authorised_breach`. The plan stays `valid = False`, because the balance really is below the safety amount, but `options()` returns nothing for a breach that every authorisation covers. So the same choice isn't offered again (Q6).
- **delay_flexible:** the planner targets the latest payment day within `due + grace_days`, and drops any early-payment discount. This is the same transformation the option's what-if already uses, moved into the planner and shared, so the two can't drift apart.

**Steps:**
1. Migration and schema regeneration; `record_override` and `end_override`, plus ending an override automatically on PAID, SPLIT or REOPENED, with writer tests.
2. `build_snapshot` reads ACTIVE overrides; the PlanSnapshot field; `inputs_sha256` covers them.
3. The planner: authorise_breach and delay_flexible handling, the `authorised_breach` flag, and options() skipping a breach that is already covered.
   - **Tests:** the worked example with Prime Chem authorised: PAY on Thu 22, lowest ₹1,83,000, no options. With Prime Chem made flexible with 7 grace days and delayed, it is paid on the latest payment day inside its grace days.
   - **Property:** no overrides gives today's result.
4. choose_option records the overrides; undo through the same route; the chosen and active state shown on Needs attention and This week.
5. Web and walkthrough tests: choose authorise → replan → PAY with the owner's reason and owner:1 events; undo → ESCALATE again; a helper → 403.
6. Gate.

**Acceptance criteria (CHG-021):**
- **AC1:** Choosing "Authorise going below the safety amount" makes each escalated bill in that plan PAY on its target day. The reason names the owner's authorisation and the gap, and the option isn't offered again while the authorisation covers the breach.
- **AC2:** Choosing a delay_flexible option moves that bill to the latest payment day within its grace days and drops its discount. The figures equal the option's own what-if.
- **AC3:** Overrides are owner-recorded events, stored in plan_override. They end by themselves when their bill is PAID, SPLIT or REOPENED, and the owner can undo one. Every move is evented.
- **AC4:** The planner stays pure: overrides arrive only through PlanSnapshot. With none, every existing planner test and golden figure is unchanged, checked by a Hypothesis property.

## CHG-023: a chosen, pending early_receipt shows as chosen (direct)

On Needs attention, an early_receipt option for a receivable is not offered again when both of these hold:
- the owner already chose an early_receipt for that receivable;
- the receivable is still open and the asked date hasn't passed.

In its place the page shows "Chosen on Mon 12 Oct: waiting for Nandi Foods' ₹2,00,000 by Fri 16 Oct". The lookup is D13's `_asked_dates` rule, shared rather than copied. Once the asked date has passed with no payment, the option can be offered again, showing "asked by Fri 16 Oct; not received".

- **AC1:** After a replan (the clock moves, or a mail arrives), the chosen early_receipt shows as chosen and pending, with no Choose button. After the asked date with no credit, it is offered again with that note.

## Questions for the PO (each has a default I'll use if the plan is approved as written)

| # | Question | Default |
|---|---|---|
| Q1 | Where does the owner say which bill a debit paid? | An `explain_txn` question, raised by code when a debit case opens, answered through the existing /questions/{id}/answer. No new route. CHG-008's agent can take over raising these questions later. |
| Q2 | Who moves the txn to MATCHED on an owner link? | The owner: a new row, bank_txn UNMATCHED → MATCHED for the owner, as your Q5 leaning in the D16 note said. |
| Q3 | Alias | Opt-in checkbox, off by default; shown only on a name mismatch; owner only; evented (PARTY_ALIAS_ADDED). |
| Q4 | The other REVIEW twins of a linked debit | Back to PAYMENT_EXPECTED, as the owner: a new payable table row, REVIEW → PAYMENT_EXPECTED for the owner. |
| Q5 | Where overrides live | A new `plan_override` table, evented through the writer, rather than columns on payable. A bill can carry both kinds, and their history matters. |
| Q6 | What authorise_breach covers | Each ESCALATE bill in the run it was chosen from, one override per bill. While every breach is covered, options() offers nothing. A new escalation later needs a new choice. |
| Q7 | How long an override lasts | Until its bill is PAID, SPLIT or REOPENED, or the owner undoes it. It doesn't expire on Monday. |
| Q8 | Size | Three changes, about 6 steps each. CHG-007 goes to batch 5 on its own, as you offered. |
