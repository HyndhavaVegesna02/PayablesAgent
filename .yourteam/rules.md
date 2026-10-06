# Rules

One rule, one line, at its rung. The story behind each -- the incident, the
date, what it cost -- lives in rules-log.md under the same ID and is read only
during an audit. Keeping them together is what makes a rules file grow forever.

A rule only lands with a falsifier: the observation that would prove it was
violated. If you can't state one, it isn't a rule -- put it in the log as a note.

Rules at lower rungs (gate commands, scripts, hooks, agent definitions,
checklists) are recorded here as one line naming where they actually live, so
an audit can see the whole surface in one place.

## Active

- R001 [prose] Human-stated conventions outrank observed codebase patterns. — falsifier: a change follows an observed pattern over a stated instruction
- R002 [prose] Tooling changes only between batches, except landing an approved rule at an existing mechanism. — falsifier: a new dependency installed mid-batch
- R003 [hook] Commits happen on the batch branch, staged file by file. — falsifier: a commit on the default branch during an active batch, or a bulk-staged commit
- R004 [gate] A change's new tests fail at its start commit. — falsifier: yt_prepatch.py exits 1
- R005 [agent-def] Reviewers never modify the tree, including via Bash. — falsifier: any tracked file changed during a review
- R006 [checklist] A consumed contract answers all four questions — units/scale, empty, absent, failure — with empty and absent answered separately. Lives in review-checklist.md. — falsifier: a merged change whose plan leaves a cell blank, or whose tests drive empty but not absent
- R007 [prose] After a fix round changes emitted output, the demo is regenerated at the post-fix HEAD and the superseded snapshot kept beside it, marked. — falsifier: a committed evidence file whose output does not match the code at that commit
- R008 [test] Only app/ledger/writer.py writes ledger tables or changes bank_account. Lives in tests/test_ledger_write_guard.py. — falsifier: that test fails
- R009 [test] All time reads go through app/clock.py. Lives in tests/test_no_direct_clock_calls.py. — falsifier: that test fails
- R010 [config] The prepatch gate runs in the project venv: .yourteam/config.yaml test_command is `uv run python -m pytest {files} -q`. — falsifier: a prepatch run whose start-commit failures are ModuleNotFoundError for a dev dependency
- R011 [prose] The public tree (the `public` remote) never contains docs/demo-script.md or docs/gmail-handover.md, in any commit, and nothing in it names them; a public rebuild drops both with the rest of the process material (batch 19's list). — falsifier: `git log public/main --oneline -- docs/demo-script.md docs/gmail-handover.md` prints a commit, or `git grep -nE 'demo-script|gmail-handover' public/main` finds a line

## Retired

<!-- Deleted rules keep one line here with the audit that removed them, so a
     future audit doesn't re-derive something that was deliberately dropped. -->
