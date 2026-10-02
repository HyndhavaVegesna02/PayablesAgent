# Batch 0 — Review

Covers: CHG-001 (repo skeleton). Branch `batch-0`, 50e14c2..26cd2d1.

## Round 1 — FIX_REQUIRED

Two major findings, both independently verified (not just read-and-assumed) by
the reviewer:

1. **AC8 violation.** `app/jobs/queue.py` called `datetime.now(UTC)` directly
   in `enqueue()`/`claim_one()`'s defaults, bypassing the `Clock` interface —
   exactly the consumer AC8 names as its own proof case. No test injected a
   Clock, so the literal claim was never proven.
2. **Foreign keys silently unenforced.** `PRAGMA foreign_keys = ON` from
   `schema.sql` only ever ran on `migrate.py`'s own one-off connection — SQLite
   doesn't persist that pragma across connections. Every other writer
   (`fixtures/seed.py`, future write paths) silently ran with FK enforcement
   off. Proven by inserting an orphan `app_user` row with no error.

Three non-blocking minors also noted: a `.gitignore` line whose exclusion
comment sat inside the pattern (never matched), `mark_failed`'s dead-letter
path untested, `app/trace/view.py`'s CLI wrapper untested.

## Fix round 1

- `enqueue()`/`claim_one()` now take an injectable `clock: Clock` parameter
  (default `SystemClock()`); two new tests inject a `FakeClock` and prove the
  default genuinely comes from it. Added `tests/test_no_direct_clock_calls.py`,
  an AST-based static guard so this regresses as a gate failure, not a review
  catch, from now on.
- New `app/db/connection.py::write_connection()` sets `PRAGMA foreign_keys = ON`
  on every writable connection; `migrate.py` and `fixtures/seed.py` route
  through it. `tests/test_db_connection.py` proves enforcement holds and
  documents the gap a bare `sqlite3.connect()` leaves open.
- All three minors closed in the same round.

## Round 2 (re-review) — APPROVE

All of AC1–AC11 re-checked, not just the two that were broken. Both major
fixes verified independently: the Clock fix by tracing what `SystemClock`'s
real current time would have produced instead (the new tests are load-bearing,
not rigged), and the FK fix by running a live probe against a real migrated
file outside the repo. `make test`: 45 passed, 3 import-linter contracts kept,
0 broken — matches the recorded gate evidence exactly. Working tree left
clean throughout both review passes.

Two new non-blocking minors surfaced (duplicated URI-construction logic in
`app/main.py` vs. `app/db/read.py`; a two-line duplicated clock-default idiom
in `queue.py`) — logged as CHG-011 and CHG-012 rather than reopening this
batch, per "nitpicks still accept."

**AC7 (CI green) remains an open item, not a defect**: nothing has been
pushed to the GitHub remote (`origin`) this session, so the workflow has never
actually run, only been verified step-by-step locally.

## Outcome

Verdict: **APPROVE**. Awaiting the human's accept/reject verdict before merge
to `main` (YourTeam: "only the human takes the final verdict, per change").
