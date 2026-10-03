# Batch 6 review

The review is split by subsystem (the lean review policy). Range: 00f8ebc..2e9bb2b.

## Round 1, CHG-018 and the shared wiring: FIX_REQUIRED

The 402 item is good: a mutation making 402 retryable fails the new test case.

Blocking:
- **B1.** check_summary ignored the amount's sign: "-₹1,83,000" passed against +₹1,83,000, and "₹20,000" passed against an overdraft of -₹20,000.
- **B2.** Numbers in words, "percent", ordinals and non-0-9 numerals (⅓, Ⅻ) passed.
- **B3.** persisted_result read the bill's full amount; a PAY line taking an early-payment discount pays less, so the diff misstated it.

Should-fix:
- **S1.** An empty note was kept as the Gemini note.
- **S2.** "rs" and "inr" matched inside words (Thurs).
- **S3.** The change docs were stale.

Nits:
- diff.py's docstring was in the future tense;
- actions.py imported bill_names through repo;
- what_if_snapshot's type and default disagreed;
- read.py imports were out of order;
- FakeBackend's optional PlanSummary was on by default;
- week.html had an inline style.

**Fixes (fix round 1, CHG-018):**
- B1: a written minus must match -value, and an unsigned amount must match +value.
- B2: number words, ordinals, percent, tomorrow/yesterday and any non-0-9 numeral now fail the check.
- B3: plan_line.amount_paise is added in migration 0004 and written by persist_plan. persisted_result reads `COALESCE(pl.amount_paise, p.amount_paise)`. A test compares the stored lines with the live plan after a discount.
- S1: an empty note fails the check. S2: `\b` is required before rs/inr.
- Found while fixing: an amount followed by a prose comma ("₹20,000, …") swallowed the comma; commas now count only between digits.
- S3: the change docs are filled in.
- Nits: all fixed. FakeBackend's optional AI is opt-in; fixture_backend() opts in for the end-to-end runs.

## Round 1, CHG-008: FIX_REQUIRED

AC1 to AC4 are met and tested; the tests are honest.

Blocking:
1. A message the agent stores (`_document_for`, status PROCESSED) is then skipped by the poll's dedup, so an unapplied bill or alert is lost.
2. A drift account can stick at CHECKING with no case:
   - (a) ask_owner allows no choices, and the owner's close never touches the account;
   - (b) a dead run_case leaves the case OPEN;
   - (c) a tool exception (for example no FERNET_KEY) crashes and retries the run.
3. A running agent overwrites the owner's close of the case (cases.save writes the status unconditionally).
4. The prompt gives run_planner the wrong argument names.

Should-fix:
- tool failures crash the run instead of being noted;
- the broad LookupError catch;
- a VALID agent invoice candidate shows on the owner's page before the case ends;
- the AC4 note says no defence failed, yet the hijacked claim reached the owner as a finding.

Nits:
- last_call is never cleared;
- the 300-character question is cut mid-word;
- there is no test that the trace holds the full tool result;
- fixture 11 is in the demo inbox;
- read.py import order.
