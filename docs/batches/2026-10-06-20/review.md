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
