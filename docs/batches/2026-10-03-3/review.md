# Batch 3 — Review

**Range:** 4988a00..086b981 (CHG-020, CHG-006). The review is split by subsystem into two reviewers, each bound by `.claude/agents/yt-reviewer.md`.

## Round 1

### Reviewer A: web layer (app/web, main, config, seed, web tests): FIX_REQUIRED

Criteria:
- AC1, AC2, AC4, AC5, AC6, AC7, AC8 and AC9 (web part) are MET.
- AC3 is PARTIAL (critical 1).
- The 10 in-scope test files: 200 passed. lint-imports: 5 kept.

**Critical** (all verified by the reviewer):
1. **The approval deadlocks after a date rollover or an unreplanned ledger write** (`app/web/actions.py:80`).
   - **What happens:** the inputs-hash check refuses, and the 409 page re-renders the same stale run, so every later approve is refused too, until some unrelated event replans.
   - **Fix:** on an inputs-hash refusal, run the inline replan in its own transaction, then render the 409 page with the fresh run.
   - **Test:** advance a day; approve gets 409 with a new run id on the page; approving with that page's form then gets 303.
2. **Dead code:** `repo.parties()` (`app/web/repo.py:369`) has no caller.
3. **Dead code:** `actions.SETTINGS_FORM` (`app/web/actions.py:493`) is never used.

**Major** (both verified):
1. **`hmac.compare_digest` on str raises TypeError for a non-ASCII token**, so the request gets a 500, not a 403. This happens at `auth.py:149` and `routes/login.py:49`.
   - **Fix:** compare bytes.
   - **Tests:** add the 'é' case to both CSRF tests.
2. **`_confirm_txn` accepts amount 0** (`actions.py:434`). BankTxnNew then raises ValidationError, a 500.
   - **Fix:** add the "above zero" field error.
   - **Test:** add a case for amount 0.

**Minor:**
- Duplicated constants: max age, weekday codes, priorities, the HX check, the question-answer UPDATE.
- Refusal handling differs between routes:
  - mark-paid's stale case goes to a generic page;
  - confirm_balance FieldErrors through `/questions` go to the generic 422 page.
- REVIEW → PAID leaves the bank_txn UNMATCHED and the case OPEN.
- confirm_balance answers every open confirm_balance question in the business, whichever account it was about.
- choices_json that isn't an object gives a 500.
- A 404 on an unknown path is Starlette's JSON, not the plain page.
- Starlette spools the whole upload to disk before the size check, and a failed insert leaves an orphaned encrypted file.
- A blank seed password creates a login with an empty password.
- choose_option doesn't check the inputs hash.
- A ca_reminder question can't be closed.
- A PAID-unlinked bill isn't shown in the day column, so the balance drop has no line explaining it.
- Stale prose in config.py (SESSION_SECRET) and in the what_if docstring.
- `_check_errors` is an identity copy of `validate.failures`.
- Stateless sessions: a copied cookie works after logout until it expires. This matches the spec.
- The seed imports `app.web.auth`.
- The async routes run sync sqlite on the event loop.

### Reviewer B: ledger, planner input, reconcile, demo, AI: FIX_REQUIRED

Criteria:
- CHG-020: all three criteria MET; no findings.
- CHG-006 (non-web half) MET: AC1, AC6 (writer side), D13, the inputs-hash normalisation and D15.
- CHG-006 PARTIAL: AC9/D12 (C1, C2, M1) and D14 (C3).
- Tests: the 13 in-scope files plus the write-guard and clock guards, 257 passed. lint-imports: 5 kept.

**Critical** (all verified by the reviewer):
1. **C1: a retried bill drops out of the plan** (`app/ledger/writer.py:419`).
   - **What happens:** PAID → REOPENED keeps matched_txn_id pointing at the reversed debit. After a failure, a retry and an owner mark-paid, the bill leaves the snapshot, so the plan overstates cash by ₹1,80,000. Its retry debit then becomes an unknown_txn.
   - **Fix:** clear matched_txn_id when a payable moves to REOPENED, or use the predicate "no MATCHED txn linked".
   - **Test:** failure → retry → owner marks paid.
2. **C2: a REVIEW bill marked paid loses its outflow on a return** (`app/web/actions.py:106`).
   - **What happens:** marking a REVIEW bill paid links the debit but leaves the txn UNMATCHED and the case OPEN. handle_failure only recognises a MATCHED txn, so a return email reverses the debit and leaves the bill PAID: the outflow is lost and the bill is never reopened. `_reviewed_debit` can also link a txn that is already REVERSED.
   - **Fix:** handle_failure honours the payable link; link only an UNMATCHED debit; resolve or annotate the case.
   - **Tests:** cover both paths.
3. **C3: DemoClock crashes on Windows when two processes touch the file** (`app/clock.py:84`).
   - **What happens:** reading and replacing the file at the same time raises PermissionError (2,715 of about 4,400 writes failed in a two-process probe). One failed read in process_one ends the worker. A failed set gives a 500 on /demo/time and a traceback from `make demo-time`.
   - **Fix:** a short bounded retry on PermissionError; OSError becomes a plain refusal.
   - **Test:** two processes, or a monkeypatched PermissionError.

**Major:**
- **M1: a PAID-unmatched bill can be subtracted twice with no owner remedy** (`app/ledger/reconcile.py:194`; verified).
  - **What happens:** the debit arrives but doesn't auto-match: a different payee name, a different amount (TDS), outside the window, or twin bills. The debit stays UNMATCHED and lowers the balance, while the bill stays an outflow. Conservative, but a false shortfall the owner can't dismiss.
  - **Fix: needs a PO call.** Either a known limit with a pinning test, or an owner "this debit paid this bill" link, or excluding a PAID bill named in an open case from the snapshot.

**Minor:**
- link_payment: its version bump and refusals are untested, and it checks neither the txn's status nor whether another payable already holds the txn.
- The role and owner checks in the new writer functions are untested with system actors or another business's owner; the 'helper:2' test fails at parse_actor before the role check.
- demo.advance writes the clock before the enqueue and commit; it should enqueue first.
- In demo mode, retry backoff and the heartbeat both use the frozen clock.
- The Monday job is keyed by the new day, not the Monday crossed, unlike the demo.py docstring.
- parse_time and the DEMO_NOW validator disagree about a time with no offset.
- The tmp name is fixed, and the forward-only check is not atomic across processes.
- The pyproject comment wrongly says the web process never loads the worker.
- match_credit's reason text names the expected date even when the D13 asked date matched.
- FixtureBackend needs an empty-text guard.
- The `_planner_status` docstring understates the CHECKING-drift double count.
- demo.advance repeats enqueue_poll_mail's logic.
- Pre-existing, not this batch: REVIEW twins.

## Fix round 1

Not started: the PO paused the session at 82% of the 5-hour usage window (2026-10-03). It resumes when the PO messages after 09:05.
