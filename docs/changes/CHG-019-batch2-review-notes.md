---
id: CHG-019
title: Batch 2 review notes not fixed in the batch
type: chore
lane:
---

## Context
Non-blocking notes from the batch 2 review (two reviewers, split by subsystem). PO policy: non-blocking notes become backlog chores.

## Description
- Reference-less duplicate alerts: two genuine same-day, same-amount debits whose alerts carry no reference share a dedup key, so the second is INVALID with no owner question. Consider AWAITING_OWNER for a reference-less duplicate (app/validate/duplicates.py).
- With MAIL_SOURCE=gmail and a key set, poll_mail is scheduled and each job dead-letters until CHG-009 (app/ingest/pipeline.py mail_source). Don't schedule poll_mail for a source that doesn't exist yet.
- The owner_question → candidate link lives in choices_json ({"candidate_id": N}); CHG-006's answer flow must read it there.
- The contract row "malformed aliases_json → [] with a trace note" has no trace note (app/ledger/reconcile.py _party_names has no tracer).
- A REVIEW bill's ambiguous_match case can point at a debit later REVERSED by a failure notice; CHG-008's agent should check the subject's current state.
- response_json_schema carries pattern, format: date and additionalProperties: false; only the authorised smoke-gemini run shows Gemini 3.8 Flash accepts them all.
- The failure-notice duplicate check matches VALID and ACCEPTED candidates, not AWAITING_OWNER ones: a resent notice whose first copy awaits the owner is processed again.
- Candidates have two meanings of "done": bank-alert candidates stay VALID once their bank_txn is written, failure notices become ACCEPTED once reconciled. Pick one when CHG-006 lands.
- confirm_balance (ASK_OWNER -> OK) does not resolve the account's open drift cases, so a later episode's dedup is fine (account subjects are not deduplicated) but the old case stays OPEN. Resolve it there too, with a test of an episode after confirm_balance (reachable once CHG-008 moves accounts to ASK_OWNER).
- tests/test_worker.py `_run_in_thread`: when its assertion fails the non-daemon worker thread keeps running and pytest hangs. Set stop (or daemon=True) before asserting.
- match_debit, match_credit and handle_failure rely on their callers for atomicity (documented; driven through the job handlers in tests/test_reconcile_jobs.py).

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-03: logged from the batch 2 review (round 1)
- 2026-10-03: two minors added from review round 3
