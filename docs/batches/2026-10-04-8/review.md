# Batch 8 review

The review is split by subsystem (the lean review policy). Range: fc6d738..2c2ae1c. Two reviewers ran in
parallel: the app code and hand-written docs, and the evals, workflow runs, fixtures and evidence reports.

## Round 1, app code: FIX_REQUIRED

The reviewer's D26 sweep found no path by which a document's first details reach `verified` without an
explicit owner approval. Only `writer.decide_bank_change(approve=True)` sets them, and only the owner can
call it. The sweep covered:
- read time;
- confirm for a new party;
- confirm for another vendor;
- duplicates;
- agent candidates;
- reject-then-redeliver.

Removing `record_bank_details` was judged right. The keyword matching, the drift refusal, the provenance
(no spoofing: only `_hand_to_pipeline` sets `found_by`) and the search operators are all met.

Major:
- **M1.** The NO_DUE_DATE stop came before the duplicate rule. A repeated bill with no due date reached the
  owner as an entry to fill, not INVALID. Before CHG-030 it was caught.
- **M2.** `schema_problems` used only `loc[0]`. A nested invoice-line error named `lines` as missing while
  also listing it as a field.
- **M3.** AC1 said the field lists are generated from the schemas. They are hand-written, and the test
  checked one direction only.
- **M4 (cross-change).** A found invoice with no due date became an INVALID candidate. The new "fix it and
  try again" line invited the agent to invent a date.

Minors:
- stale comments, a docstring count and reason texts;
- `_since` on a date-only opening balance;
- `_senders` repeats `accounts_of`'s parsing;
- Gmail's unpadded dates;
- the note's resumed exemption;
- a first account number at an IFSC on record wasn't flagged;
- rejecting an entry left its bank proposal open;
- the invoice path was tested only at check level;
- no test for a misspelt tax-type key;
- statement rows the agent found didn't carry the case;
- a module-level config read in a test.

**Fixes (778e75e):**
- M1: the duplicate rule ignores a NO_DUE_DATE failure and runs before the stop. Tests: a repeated voice
  note and a re-sent invoice, both with no date, are INVALID.
- M2: nested paths (`lines.0.amount_text`), and the line's own fields listed. Test.
- M3: the test parses the prompt's bullets and checks both directions, for both records and the line. AC1's
  "generated" is met by this two-way check, not by rendering. The prompt is unchanged, so the AFTER run's
  prompt version still holds.
- M4: an invoice candidate whose only failure is the missing date is VALID evidence. The reply says to
  leave due_date null; the owner fills it when the pipeline reads the handed-on message. Test.
- Minors fixed:
  - a first detail of either kind is flagged;
  - rejecting an entry withdraws its bank proposal and resets the vendor unless another is open;
  - statement rows carry the case;
  - `_since` keeps a date-only value;
  - unpadded dates are accepted;
  - comments, reason texts and the note are corrected;
  - config.yaml says what a missing statutory block means;
  - tests cover the emailed-bill path, the misspelt key and the date-only value.
- Minors not fixed:
  - `_senders` stays a small local reader: `accounts_of` returns a different shape (frozenset, lowercased);
  - the module-level config read was noted only.

## Round 1, evals and workflow runs: FIX_REQUIRED

The reviewer regenerated every fixture report in scratch at HEAD. All match the committed 2142c95 reports
line for line. The superseded copies are byte-identical to fc6d738, and the live BEFORE and AFTER name
their commit, prompt version and cost. Correcting the canned Sharma reply to null was judged legitimate:
it was a guessed year, against the prompt. The replay test exercises the real path.

Major:
- **M1.** `OwnerFormRefused` scored every form refusal as extract. A rule-check refusal (`entry`) or an
  app-side value was blamed on the model.
- **M2.** `flagged_fields` copied the page's flag rule.
- **M3.** The fixture index still named fixture 22's old description.

Minors:
- no index row for the AFTER;
- the fill guard was untested at the step;
- WRONG dropped the live call's `reference`;
- fixture 22's wording wasn't noted as chosen;
- `approve_bank_details` approved every open question;
- the PO-required checks weren't pinned;
- the bare harness's new sentences were untested;
- import order.

**Fixes (7c80499):**
- M1: a refusal is extract only when every refused field was read from the document and left as read.
  `entry` is validate, and anything else stays a crash. Tests cover each case.
- M2: one rule, `attention.flagged_fields`, used by the page and imported by the runner.
- M3: the row is corrected.
- All minors are fixed. `approve_bank_details` now names its invoice; scenario 09 approves AP/2610/131's
  details only.

Every fixture report regenerated at 7c80499 into scratch matches the committed 2142c95 reports below their
headers, so no evidence changed and none was regenerated.
