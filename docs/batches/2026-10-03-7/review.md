# Batch 7 review

The review is split by subsystem (the lean review policy). Range: 886da0b..4e7a913. Three reviewers ran
in parallel: the app code (CHG-010b, CHG-027's product fix), the evals and the workflow runs (CHG-010a,
CHG-027), and the evidence documents (CHG-010c, CHG-027's docs).

## Round 1, app code: FIX_REQUIRED

Blocking:
- **C1.** `owner_alert` was UNIQUE on (business, kind, ref) whether or not the row had been sent. A second
  balance mismatch on the same account, or a bill returned twice, never emailed the owner again.

Major:
- **M1.** `_settle_debit_question` (reached from mark-paid, and from explain_debit's "settled meanwhile"
  branch) closed the case but left the case's agent question OPEN. This was W2's defect on a sibling path.

Minors:
- a URL or email address in a stored name survived cleaning;
- the money_received test read alert_line rather than the email that was sent;
- STARTTLS and the SMTP login weren't asserted;
- the U+2028/2029 separators were written as raw characters, and bidi controls weren't stripped;
- a blank APP_BASE_URL gave a bare link;
- the except comment was narrower than the code;
- unsent alerts after a dead job wait for the next alert (undocumented);
- a stale "lowest balance" line is possible if a queued send runs before a replan;
- one bad alert row blocks the digest;
- the unexpected_debit wording is also used for ambiguous matches;
- the plan's throttle "Shown by" wording.

**Fixes (044482b):**
- C1: a partial unique index, unsent rows only, edited into 0005 in place. **Batch-7 dev databases need
  `make reseed`.** Test: an alert sent, then the same event weeks later sends a second email.
- M1: `_settle_debit_question` goes through `_settle_case`. Test: mark-paid answers the agent question.
- Minors fixed:
  - names lose web and email addresses, bidi controls and separators, now written as escapes;
  - the sent email, STARTTLS and login are asserted;
  - a blank base URL falls back to the default;
  - the comment is corrected;
  - the requeue behaviour is documented in alerts.py.
- Minors not fixed, noted here:
  - the stale-line ordering and the one-bad-row digest: low likelihood, the ledger is append-only. They
    belong to a future alerts change;
  - the ambiguous-match wording was the plan's approved choice;
  - the plan's throttle "Shown by" text says "one email with three lines". The tested behaviour sends the
    first at once and digests the rest. That is the intended throttle; the plan text was loose.

## Round 1, evals and workflow runs: FIX_REQUIRED

The reviewer re-ran every report and the fixture generator in scratch and confirmed:
- every committed report matches line for line;
- the 13 new alerts' balances match their arithmetic;
- W1's ₹2,75,610 and W5's ₹34,910 check out.

On the scenario 7 path check they judged it legitimate, not rigging, but scored at the wrong level.

Blocking:
- **C1.** Workflow run A's `helper-cannot-confirm` posted a fake CSRF token, so the 403 came from the CSRF
  check and the check could not fail.

Major:
- **M1.** Checks that pin the fixture AI's own path counted toward end-to-end success:
  - scenario 10's refused tool, scenario 8's medium-then-high, and workflow B's agent-tool-refused would
    fail a correct live model;
  - scenario 7's trajectory check was scored as end to end.
- **M2.** The workflow harness copied the runner's drain without its wait for retries. The world builder,
  the fixture lookup and START were each written two or three times.

Should-fix:
- S1: the ablation named a "winner" for a negative drop.
- S2: hasattr silently skipped renamed seams; the checks left on weren't disclosed.
- S3: patching `bank_txn_with_key` also disabled the dedup-key loop.
- S4: approve() took any 409 as stale; the tick check accepted any 409.
- S5: case helpers passed vacuously when a debit was missing.
- S6: an error outside a step wrote no report; the ablation exited 0 when ABORTED.
- S7: many checks had an empty `why`.

**Fixes (7caab40, 729371c, 5f3c463):**
- C1: the helper posts their own valid token, and the check asserts the role refusal's text. Probed: with
  the role rule lifted the post gets 422, so the check fails.
- M1:
  - expectations have a `level` (end_to_end or trajectory) and a `fixtures_only` flag;
  - success is decided by end-to-end checks only. Trajectory checks get a Path column, a "Path failures"
    section and a totals count;
  - live runs leave fixtures-only checks out;
  - scenario 7's check is trajectory; scenario 8's and 10's are trajectory and fixtures-only;
  - workflow B's agent-tool-refused runs offline only.
- M2: one `drain_jobs` (the workflow waits by moving the demo clock), one `fresh_world`, one
  `find_fixture` and one START, shared by the runner, the bare harness and the workflow runs. Owner email
  capture is per run.
- S1–S7 fixed:
  - `top > 0`;
  - a renamed seam raises;
  - duplicates are blanked where each check is called;
  - `RULE_CHECKS_LEFT_ON` is in the report;
  - approve() tells stale from refusal, and the tick check reads the refusal text;
  - helpers raise on a missing debit;
  - outside-step errors are reported, and the ablation exits 1 when ABORTED;
  - every check has a why, and a test keeps it so.
- Minors fixed:
  - `git_commit` counts untracked files, except its own reports folder;
  - `Decision` is public;
  - the fixture README says why 31 isn't 13;
  - the golden balances are read from their day rows;
  - the bare harness's Nandi sentence no longer says Nandi agreed.
- Minor not fixed: fixture-mode report headers name the configured model. The Mode column and banner say
  it is fixture mode.

The superseded reports are kept, marked, in `docs/evals/superseded/before-review-round-1/`. Every current
report was regenerated at 5f3c463 from a clean tree. The regression report now reads: 55 of 55 succeed on
their end result, and path checks held in 10 of 15 runs (scenario 7 fails its path in all 5).

## Round 1, evidence documents: FIX_REQUIRED

The reviewer verified these against the code and tests:
- every control-point row in the architecture;
- the attack narrative against test_ac4;
- every trace line number;
- the generated tables;
- the README's commands, env names and known limits.

Blocking:
- **B1.** Walkthrough step 4 (and the demo script's 1:05 row, and the threat model's bank-change row)
  claimed a bank-change flag. The flag fires only when the vendor has details on record, and the
  walkthrough never confirmed AP/2610/131 first.
- **B2.** The README said app/validate lifts out with `money.py` alone; it also needs `time.py` and
  `names.py`.
- **B3.** The D25 test missed almost every figure format the reports print.

Should-fix:
- S1: the citation test ignored links and `::symbol`s.
- S2: the demo-only route was missing from the generated table.
- S3: make_traces didn't check its runs' results.

Minors:
- the traces README overstated what the test pins;
- the model field on fixture traces;
- "every write tool was refused" (add_candidate ran and came back INVALID);
- the singular voice fixture;
- "every debit and credit matches" for run A;
- the write-guard exemption wasn't in the permission model;
- "his" in CLAUDE.md's intro and a writer.py comment.

**Fixes (9d3ad6c):**
- B1:
  - the walkthrough and the demo script confirm AP/2610/131 on Tuesday;
  - the threat model and README state the limit;
  - the product gap is drafted as **CHG-029, for the PO**: a vendor's first bank details are recorded
    without a flag.
- B2: all three files are named, and a test checks the list against the package's imports.
- B3: the detector covers N of M, N/M, N passed or failed, model calls, µUSD, US$ and rate, with a
  self-test of ten known-bad lines.
- S1:
  - links and `::symbol`s are checked, with a self-test;
  - a symbol cited by its start (`test_ac4_...`) matches by prefix;
  - config.yaml, pyproject.toml and the Makefile are checked too.
- S2: the demo route is listed as "demo mode only".
- S3: make_traces refuses a run that isn't the success, or the path failure, it stands for.
- Minors fixed: all except the pronouns, which are outside the batch's diff. CLAUDE.md is the user's file.
