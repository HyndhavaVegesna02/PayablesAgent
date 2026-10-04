# Batch 19: the public submission

PO-directed and PO-verified (payablesagent-ac, 2026-10-05). No live spend.

- Branch `submission` was cut from main at c7ebdc8. It drops the process material (.yourteam, .claude,
  docs/batches, docs/changes, docs/notes, docs/evals/superseded and invalid, CLAUDE.md, the Gmail handover and
  the hackathon brief) and moves the TDD to docs/design/. It strips every process reference from the code,
  tests, config and docs, renames the process-named tests by behaviour, and defines the kept decision labels
  once in architecture.md. It regenerates the fixture reports, and redacts the process phrases from the prose
  of 18 live reports, with no data changed.
- Branch `public` is an orphan: one commit, 36624a3, with the submission tree. It was pushed only to the
  `public` remote's main (https://github.com/HyndhavaVegesna02/PayableAgent.git) on the PO's instruction.
  origin is untouched.
- Verified: make test (1584 passed), make check-evidence (all 7 reproduce), lint-imports (9 kept), both
  process-reference greps empty across the whole tree, and no secrets.
- Known and left: the bare ablation invocation's header says COMPLETE although its last run stopped on the
  cost cap. That run is ERRORED and unscored. The fix, checking the guard after the last run, is for a later
  batch.
