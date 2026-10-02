# Batch 2 — Review

Changes: CHG-013 (worker, replan, persisted plans), CHG-004 (alert ingestion), CHG-005 (reconciliation and drift). All three are `planned`.

The diff is about 5,500 lines, so the review was split by subsystem. Each reviewer ran as a general-purpose agent bound by `.claude/agents/yt-reviewer.md`:
- **Ledger and jobs:** CHG-013 and CHG-005.
- **AI and ingestion:** CHG-004.

Both read the seams: handler registration, PermanentJobError, the pipeline's routing, and transaction boundaries. Neither opened `.env` or made a live Gemini call.

## Round 1: both FIX_REQUIRED

**Ledger and jobs: 2 critical, 5 major**
- Critical: `record_reported_balance` compared report times as strings. An alert whose Date header was in UTC lost to an earlier IST one, which produced a false drift case.
- Critical: the atomicity test wrapped `match_debit` in its own transaction, supplying the property it claimed to check. Removing `writer.atomic` from all three handlers passed 138 tests.
- Major: an alert with no balance queuing no drift check was untested.
- Major: a refused heartbeat (Windows `os.replace` onto an open file) or a busy database stopped the worker.
- Major: an unknown debit didn't replan.
- Major: `calculated_balance` duplicated the `account_balance` view.
- Major: `worker.main()` (`make worker`) was untested.

**AI and ingestion: 3 major**
- Redaction by whole word missed compounds: `apikey`, `dbpassword`, `fernetkey`.
- A failed confidence check went back to the model, which could drop the flag and slip the record past the owner. That contradicts the plan's rule and the TDD.
- Three absent cases in the contract grid were untested: Message-ID, From, and `APIError.code` None.

## Fix round 1: 7f54ded (AI and ingestion), c0727b2 (ledger and jobs)

- Report times are compared as instants and stored in IST.
- Atomicity is now driven through the real handlers with `process_one`, by crashing between the paired writes.
- The worker loop survives OSError on the heartbeat and OperationalError on the database.
- An unknown debit replans.
- With no date, `calculated_balance` is the view; a Hypothesis test checks the dated cut.
- `main()` is tested.
- Redaction is by word ending.
- A confidence failure goes straight to AWAITING_OWNER.
- The absent cases are tested.
- Minors fixed:
  - `requeue_running` counts the interrupted attempt;
  - `reconcile_failure` marks its candidate ACCEPTED and is a no-op on re-run;
  - a reversal while CHECKING rechecks the gap;
  - a document stored under another key dead-letters at once;
  - outages are traced;
  - search sorts by time;
  - one body-text rule;
  - the trace viewer falls back to Settings;
  - one DEFAULT_BUSINESS_ID;
  - the Monday plan has a misfire grace.

Deferred notes went to CHG-019.

## Round 2: both FIX_REQUIRED

- Ledger and jobs, critical (a regression from round 1): `open_case` deduplicated on any OPEN case for the same subject. A second, unrelated drift episode on the account reused the first episode's case, with its stale stake, thinking level and facts.
- Ledger and jobs, major: widening the failure-notice duplicate check to ACCEPTED was untested.
- AI and ingestion, critical (missed in round 1): the no-Date test stripped the header with an LF-only byte replace. On a fresh clone (`core.autocrlf=true`), `make test` failed 1 of 612.

## Fix round 2: e66e55b

- `open_case` deduplicates only per-event subjects (`bank_txn:`, `candidate:`). A gap that closes resolves the account's open drift case. A two-episode test was added.
- A resent return email after reconciliation is INVALID, with no case and one REOPENED.
- The worker requeues after a busy-database error.
- The no-Date test drops the header line by line.
- `fixtures/test_inbox/*.eml` are `-text` in `.gitattributes`. A `git archive` export passes 617/617.
- As-built notes were added to the plan and change files.

## Round 3: both APPROVE

At 4ae3d45 (code e66e55b), `make test` passes 617 tests and the 4 import-linter contracts are kept. Two minors went to CHG-019:
- `confirm_balance` (ASK_OWNER → OK) does not resolve open drift cases. The path is unreachable until CHG-008 moves an account to ASK_OWNER.
- A failing assertion in `test_worker._run_in_thread` leaves a non-daemon thread running, so pytest hangs instead of failing.

## Open for the PO

- `make smoke-gemini` (at most 3 live calls) has not been run. It is the only evidence that the prompts and the `response_json_schema` keywords (`pattern`, `format: date`, `additionalProperties: false`) work on Gemini 3.8 Flash itself.
- Narrowing to note: CHG-004 AC4's "a failed check triggers one re-extract" does not apply to an uncertain field, which goes to the owner at once (plan rule and TDD).
