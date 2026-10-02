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

### Reviewer B: ledger, planner input, reconcile, demo, AI

Pending.

## Fix round 1

Not started: the PO paused the session at 82% of the 5-hour usage window (2026-10-03). It resumes when the PO messages after 09:05.
