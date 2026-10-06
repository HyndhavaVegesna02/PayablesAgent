# Batch 20 review

## Round 1 (yt-reviewer, d2c1849..9f7cfbe): FIX_REQUIRED

Ran: the 13 touched test files (449 passed), the full suite (1828 passed), check-evidence (all 8 reproduce).
R100 confirmed for every live raw report; the scenario 04 commit-by-commit claim replayed independently.

Blocking:
- B1: the suite page's "planned" was inferred from the rows that exist, and the stopped-invocation sentences
  (suite and ablation) can be false (an unrun scenario; a stopped re-run of finished work; a — cell whose run
  was reached and errored).
- B2: the "earned the most" arithmetic sentence is false when the full system missed a paired run or the
  knock-out won one the full system lost.
- B3: with no full-system row, the page says no knock-out passed the threshold.
- B4: plain_status hard-codes the 429 for any spend-cap stop; no contract test against the guard's own stops.
- B5: the README figure detector misses number words and other digit forms; the READMEs quote counts no test
  asserts; nested hand-written READMEs aren't scanned.
- B6: prose naming moved folders (the archive READMEs; scenario 08's path-budget comment).

Minor: duplicated pct; "at commits X and X"; the 1-eval-report README's reason for three invocations;
report.main links from a folder outside docs/evals; an overlong README line; two link checkers.

## Fix round 1 (bf31b1c, pages regenerated at 15df696)

B1 plan recorded and named; B2 arithmetic only where exact; B3 no-full sentence; B4 codes kept, contract test
through a real BudgetGuard; B5 stricter detector, derived quotes, run-folder notes out of scope (pinned); B6
archive names mapped in "Start here" (archives left as written, PO); minors.

## Round 2 (yt-reviewer, d2c1849..81add20): FIX_REQUIRED

B2, B3, B4, B6 closed; the B5 scope decision accepted. Blocking:
- 1 (B1 again): "a stopped invocation's finished runs ... are counted here" is false where a later invocation
  replaced some of them (live-baseline gives 30 of its 35; v2-full 30 of 31); "ran in another invocation"
  doesn't follow from no planned run missing (a later stopped invocation's errored runs ran nowhere).
- 2 (B5 again): the detector passes digits before an unlisted noun, single-digit hyphen forms ("9-point"),
  "(416)", and number words it doesn't list; some result claims in words aren't asserted.
- 3 (new, R007): no superseded snapshot was kept of the reports this batch regenerated, and "Start here"'s
  line on superseded/ is then false.

Minor: _rows fixtures keep budget.stopped; scenarios outside the plan; "1 runs" / "1 ablation invocations";
_CODE unanchored; long README lines; "moved unchanged" for a note whose paths were updated.

## Fix round 2 (16eefcd, pages and snapshots at 0f34c5a)

Stopped sentence says only what the page shows; any digit outside a quote or a name is a typed figure, and
word claims are derived; superseded snapshots kept (R007).

## Round 3 (yt-reviewer, d2c1849..7c6420d): FIX_REQUIRED

Round 2's 1 and 3 closed (Runs used checked by an independent script against all 26 sources; the 22 snapshot
files byte-identical to their commits). Blocking: the fix's year allowance (`\b20\d\d\b`) lets any number
from 2000 to 2099 through ("2048 calls", "spent 2050 µUSD"), a regression from 16eefcd; the NxM shape
allowance is as wide. Minor: other allowances wider than their names (scenario-ID lists, "a 4xx", list
numbers); number words caught only before a listed noun; ordinal claims about raw runs not derived; the
round-2 snapshot README names a page that didn't change; the default plan isn't said on the page, and a
source with no runs per scenario plans 0; modes can be mixed.

## Fix round 3 (efaeb64, page and snapshot at d01e0a8)

A year passes the figure check only inside a date, the suite's shape only as 11x5/14x5; scenario-ID lists take
only scenario numbers; number words other than "one" count anywhere; every round-3 probe is a test. The page
says when planned runs per scenario are the default; a plan with no runs per scenario and mixed modes are
refused; the round-2 snapshot holds only the pages round 2 changed.

## Round 4 (yt-reviewer, confirmation of fix round 3): APPROVE

Round 3's blocker closed (each new probe fails on the old detector and passes on the new; every digit span the
allowlist blanks in the six READMEs is a real name). No regression or new false sentence. Minor only, filed as
CHG-056: a counted-noun guard on the scenario-ID and dated-year allowances; a single-digit list number at the
start of a wrapped prose line; bare "one" and some fraction words; a message check on the plan-runs error; a
mixed-mode test for ablation_combine; two long README lines.

Ready for the PO's verdict. Gates of record: make test and make check-evidence green at d01e0a8 (c6b8ac5).

## Verdict

PO (payablesagent-ac), 2026-10-06: CHG-055 ACCEPTED. Verified independently at the public commit ce968db: pytest
1770 passed, 9 import contracts kept, check-evidence 7 of 7; only comment lines changed in app/; 749 live files
R100; the only process word left is the live report's own label. Accepted: the figure rule leaves the two notes
kept inside run folders out; the 8 public rewordings. Pushes authorised: public-ui to the public remote's main,
dev to origin main, both fast-forwards. CHG-056 also takes a test-derived headline for 2-harness-ablation's
offline row (empty today).
