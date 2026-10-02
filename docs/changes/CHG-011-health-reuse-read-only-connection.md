---
id: CHG-011
title: main.py's /api/health should reuse read.py's read_only_connection()
type: chore
lane: direct
---

## Context
Surfaced as a non-blocking minor note during batch 0's re-review.
`app/main.py`'s health handler hand-builds the same `file:<path>?mode=ro` URI
and bare `sqlite3.connect(uri=True)` pattern that `app/db/read.py::read_only_connection()`
already provides. Both are correct today, but a future change to the URI
construction (e.g. adding another pragma) would silently miss main.py's copy.

## Description
Replace `/api/health`'s inline connection code with a call to
`app.db.read.read_only_connection()`.

## Acceptance Criteria
- [ ] AC1: `/api/health` calls `read_only_connection()` instead of constructing its own URI
- [ ] AC2: Existing tests/test_health.py tests still pass unchanged

## Expected paths
<!-- direct lane: not required -->

## Open Questions
<!-- none -->

## History
- 2026-10-02: drafted from batch 0's re-review minor note
- 2026-10-02: ACCEPTED at batch 1 verdict (PO).
