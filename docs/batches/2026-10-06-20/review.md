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
