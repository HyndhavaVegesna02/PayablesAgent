# Batch 23 review: the shrimp rehearsal holds under live variance (CHG-061)

One yt-reviewer read the batch, range 9feec65..922cf35, then the fix round.

## Round 1 (922cf35): FIX_REQUIRED

AC1, AC3, AC4, AC5 and AC6 met; AC2 partial. Moves 1 and 3 find their bills by amount and normalised number; the
misread test puts the ₹12,15,000 Ravi entry ahead of 1042 and the fortnight still passes. The reworded 02 and 06
still sort as payment confirmations offline, and the agent still resolves both credits. The canned replies for
the user's real files match live rehearsal 1's traces field by field (job-15, job-16); both files are git-excluded,
and an export without them passes every shrimp test. The doc's tidy-the-vendor claim checks out against
names.py (one-directional) and reconcile.match_debit. No app/, prompt or protected path changed. Two majors:

- **The doc's offline quotes were stale for the real files.** With the canned replies in place, the offline
  rehearsal and FALLBACK=1 render "Raju petrol bunk, ₹3,000", the live transcript and "VENKAT MOTORS/Aerator &
  Pump Repairs, Bhimavaram, ₹18,000" on this machine; docs/demo-shrimp.md quoted only the placeholders and
  called the header-line vendor live-only. The quotes test pinned the placeholders, so it could not catch this.
- **no-bill-from-the-buyer was keyed by an exact party name** (`pt.name = 'Ravi Traders'`), in the driver and in
  play(). A payable made from 02 or 06 under "RAVI TRADERS" or the signature line would have passed. AC2 asks
  for no payable *for that email*.

Minors: planned_bill's docstring; INVOICE_0931/1042's unread fields (pass them to confirm()); a "sorted as None"
note when an email is never sorted; the before-and-after plan comparison only shows rejecting doesn't move it;
MISREAD_02 not verbatim from live; a circular canned-reply assertion; the lookup test lacked a same-amount pair;
the doc's misread line covered only 02 and promised more than the rewording can; batch.yaml's started time.

## Fix round 1 (a36f023)

The buyer's-record check counts payables joined on source_document_id where external_ref is the email, plus that
email's entries still waiting; it expects (0, 0, True), and play() counts the same way. The doc says its quotes
are on the placeholder uploads and that, with the real files present, offline replays live rehearsal 1; move 4
quotes both sets. A new test builds the real-file question bodies the pipeline's way from the canned replies, so
no file is needed. Every minor fixed: confirm() gets INVOICE_0931/1042, the note says "not sorted (doc_type
empty)", the plan comparison is commented, MISREAD_02 is verbatim, the circular assertion is gone, the lookup
test has 1041/1042 at one amount and refuses an amount-only lookup ("2 waiting bill"), the doc's misread line
covers both records and says the rewording is "meant to" lower the chance, started is 00:11:04.

## Round 2 (a36f023): APPROVE

Both majors fixed; AC1-AC6 met; tests/test_shrimp_profile.py 30 passed, ruff clean. Two minors:

- direct-gates.txt lacked the evals and driver output: the close run (direct-gates-close.txt) carries both.
- The doc-quote test copies pipeline.py:427's sentence template rather than calling it, so a change to the
  template is caught only when the doc stops matching the copy. Acceptable at this size; to CHG-059.

## Verdict

PO (payablesagent-ac), 2026-10-08: CHG-061 ACCEPTED, on the dev's direct-command evidence at a36f023
(direct-gates-close.txt, committed at f311ee6: pytest 1975 passed, 9 contracts kept, 8 reports reproduce; evals
fixtures 14/14; the offline driver 7/7) and the PO's own scope review: 6 non-bookkeeping files, all demo-only
(scripts/rehearse_shrimp.py, tests/test_shrimp_profile.py, docs/demo-shrimp.md, fixtures/shrimp_ai_replies.json,
fixtures/shrimp_inbox/02 and 06), and no app, protected or prompt path. The PO's own verification run in
C:\Hyn\PayablesAgent-uicheck was killed by the machine's low memory, not by the code; the user chose to accept
on the dev's evidence. make stayed blocked by Application Control; its red entries stay. Push authorised: dev to
origin main; the public and submission repositories untouched. Live rehearsal 2 authorised next, once, capped at
$1.00, no retry.
