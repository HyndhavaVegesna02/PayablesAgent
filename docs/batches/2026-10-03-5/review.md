# Batch 5 — Review

**Range:** 5e8b6ad..3ac8f76 (CHG-007, slices S1–S8). The review is split by subsystem into two reviewers, each bound by `.claude/agents/yt-reviewer.md`:
- **A, document side:** ai, ingest, validate, domain, db/read, fixtures.
- **B, owner and ledger side:** web, ledger.

## Round 1

### Reviewer B: owner and ledger side: FIX_REQUIRED

**Critical:**
1. **A bank change was bypassed when the owner corrected the vendor on confirm.**
   - **What happened:** the pipeline compares a bill's bank details only for the vendor it read. A near-spelling ("Ashirvad Papers") matched no vendor, so nothing was flagged. When the owner then confirmed the bill as "Ashirwad Paper Suppliers", the confirm step did not compare either (`record_bank_details` only fills empty details). The reviewer verified this by probe.
   - **Fix:** `writer.flag_bank_change(party, candidate, last4, ifsc, actor…)` compares, flags and asks in one place. The pipeline calls it, and so does confirming a bill whose vendor already has details.
   - **Test:** `test_c1_a_bill_confirmed_for_another_vendor_than_it_was_read_as_is_still_compared`.

**Major:**
1. **Deciding one proposal closed every bank-change question of the vendor,** so a second (fraudulent) proposal vanished. Probe-verified.
   - **Fix:**
     - only the decided candidate's question is answered;
     - another open proposal that still differs from the details now on record keeps the vendor change_pending, and one that matches is settled;
     - a candidate that is not a pending proposal is refused.
   - **Test:** `test_m2_deciding_one_proposal_keeps_another_open_and_the_vendor_pending`.
2. **A vendor's first details were stamped verified from a card that never showed them.**
   - **Fix:** the confirm card shows "Bank details on this bill: account ending NNNN, IFSC …".
   - **Test:** `test_m3_…`.
3. **The question-close SQL was copied again.**
   - **Fix:** one `_close_open` helper is used by confirm_record, approve_bank_change, unlock_pdf and ca_reminder.
   - `_answer` and `confirm_balance` keep their own SQL: they close by question id and by account, a different shape.

**Minor (fixed):**
- The D20 warning now shows on the "Approved, waiting to be paid" rows too (tested).
- Unlock writes the file last.
- An overdue MISSING amount warns too (tested).
- The statutory payable's fields live in one helper.
- Supplying a tax amount twice is refused (tested).

**Minor (deferred, to the backlog):**
- An approved proposal that printed only an IFSC keeps the old account with the new IFSC.

### Reviewer A: document side: FIX_REQUIRED

**Major:**
1. **Confirm re-checked duplicates with a weaker rule,** so the same invoice could become two payables. Probe-verified: a confirmed email invoice plus an unsure photo; and a typed entry of an invoice already waiting.
   - **Fix:** `entry_checks` asks `invoice_on_record` (skipping the entry being confirmed). Invoice numbers compare letters and digits only (`normalise_invoice_number`); bank references are unchanged.
   - **Tests:** `test_doc_m1_…` (both cases).
2. **`parse_spoken_inr` guessed on an elliptical amount.** "ek lakh pachaas" gave ₹1,00,050 and "dedh lakh do" gave ₹1,50,002.
   - **Fix:** a bare number right after lakh or crore is refused. Negative amounts are refused.
   - **Tests:** `test_doc_m2_…`. A bare tail after hazaar or sau still reads ("do hazaar pachaas"); that test passes before the fix by design.
3. **Two identical statement rows collapsed into one,** leaving the ledger ₹590 short and causing a false drift.
   - **Fix:** every row the ledger did not account for is added, with an ordinal on a colliding dedup key.
   - **Test:** `test_doc_m3_…`, which also covers rows before the opening date being left alone.

**Minor (fixed):**
- A voice amount must be words the transcript holds, so a model's own figure fails the amount check (tested).
- The validate README lists every module.
- The fixture script docstring is current.
- The AC6 exit test scans for the wrong password too.

**Minor (deferred, to the backlog):**
- A round-off the model files under `lines` sidesteps the D19 cap, and the retry note gives the shortfall. Both rely on honest labelling.
- An emailed statement must come from an alert sender.
- Two locked PDFs with different passwords in one email can't be unlocked.
- A lone "45" reads as ₹45.

### Fix commit

ee819fa. The gate is recorded under CHG-007: green, 1034 passed, ruff clean, 6 contracts kept.

`yt_prepatch --since 3ac8f76`: PASS. 16 tests fail at 3ac8f76. The ones that pass there are guards that hold before and after: a bare tail after hazaar or sau, and "minus pachaas hazaar", which was already refused.
