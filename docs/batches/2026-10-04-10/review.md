# Batch 10 review

One reviewer read the whole batch (small, direct lane), range 6f0e795..241c78b.

## Round 1: FIX_REQUIRED

The reviewer found CHG-033's stripping safe. Every word the prefix rule can drop starts with "rup" or is
exactly rs or inr; no number, scale or fraction word qualifies. The parser and the said-words comparison
strip the same words. CHG-035 counts honestly, and its re-derivation catches a hand edit. The markdown refactor changed
no committed report. Every claim in CHG-036's README checks out against the reports and traces.

Major:
- CHG-034 made a marked field with no scenario value a ScenarioGap (crash). Only scenario 04 stated its
  values, so a live misread in 03, 05 or 09 would show as a crash instead of the model's extract failure.

Minors:
- two drifted currency lists;
- a pre-existing substring hole in the voice check;
- the bare harness now hears scenario 04's fill;
- "Not given" was shown for any empty due date;
- the owner-typing rule was written twice;
- workflow A's "one field" text;
- combine relied on argument order, let an all-errored row win, and accepted a single part;
- check-evidence crashed with a traceback on a missing source;
- two README wordings;
- the extract attribution's test is mocked.

**Fixes (c88f511, 94e46d8):**
- the major: scenarios 03, 05 and 09 state their documents' party, amount and due date. 03's fields-read
  check now reads the candidate as read, and a test holds every confirming scenario to this;
- one currency vocabulary, with rupaya, rupaiya and rupye;
- "Not given" only when the document gave no date;
- one `owner_typing` rule;
- the step text is corrected;
- combine sorts by date, keeps finished runs over all-errored ones, needs two or more parts, and records
  config and variant;
- check-evidence names a missing source and restores the working directory it changes. The full suite
  caught that leak;
- the README wording is corrected;
- the substring hole is drafted as CHG-037 for the PO;
- the bare harness hearing scenario 04's fill is noted for the PO before a live ablation.

`make check-evidence` then found workflow A's report stale: its Saturday step's text had changed. It was
regenerated at c88f511, and the old copy is kept, marked, in `docs/evals/superseded/before-batch-10/`.

## Round 2: FIX_REQUIRED

Re-review of c88f511 and 94e46d8. The round-1 findings are resolved except one part of the major: scenario
03's fields-read check read the candidate's number, amount and party, but not its due date. That is the very
field the owner now types. A run where the model missed the handwritten due date passed with no failed check.

Minors:
- the combined page's prose still stated the old replacement rule;
- the CLI description said "oldest first";
- this file's round-1 wording "its re-derivation can fail" read as a defect.

Scenarios 05 and 09 also let the owner type fields that no check reads. Their passes_when isn't about field
extraction (one payable; bank details flagged), so this is a deliberate choice, recorded here.

**Fixes:**
- 03's fields-read check includes the candidate's due date. A test runs 03 with the due date missed and
  asserts FAILED at extract;
- the prose, the description and the wording are corrected.

