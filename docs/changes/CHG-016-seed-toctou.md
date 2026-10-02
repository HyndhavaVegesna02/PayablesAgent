---
id: CHG-016
title: Seed robustness
type: chore
lane:
---

## Context
fixtures/seed.py checks AlreadySeeded before opening its write transaction (a check-then-act gap). Harmless for a single-user dev tool; move the check inside writer.atomic(). (The DATABASE_PATH-via-Settings fix and Windows PermissionError on --fresh were folded into CHG-013 by the PO.)

## Description
<!-- to be written when planned -->

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: logged from batch 1 review notes (PO: non-blocking notes become backlog chores)
