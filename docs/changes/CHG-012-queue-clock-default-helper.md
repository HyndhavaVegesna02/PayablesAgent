---
id: CHG-012
title: Dedupe queue.py's "(clock or SystemClock()).now().isoformat()" idiom
type: chore
lane: direct
---

## Context
Surfaced as a non-blocking minor note during batch 0's re-review.
`app/jobs/queue.py`'s `enqueue()` and `claim_one()` both repeat
`(clock or SystemClock()).now().isoformat()` verbatim. Two lines, low risk —
genuinely optional, logged only so it isn't silently copy-pasted a third time
as the module grows.

## Description
Factor the idiom into a small private helper (e.g. `_now_iso(clock)`) if/when
a third call site appears; not worth it for two.

## Acceptance Criteria
- [ ] AC1: No behavior change; existing tests/test_jobs_queue.py pass unchanged

## Expected paths
<!-- direct lane: not required -->

## Open Questions
<!-- none -->

## History
- 2026-10-02: drafted from batch 0's re-review minor note
- 2026-10-02: rejected — PO dropped: entry's own text says not worth it for two call sites
