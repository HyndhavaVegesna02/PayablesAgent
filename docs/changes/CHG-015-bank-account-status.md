---
id: CHG-015
title: Define bank_account.status values
type: chore
lane:
---

## Context
bank_account.status (default 'active', no CHECK, not in the TDD's value sets) is not read by build_snapshot, so a closed account's balance would still count in opening cash. Decide the values and whether non-active accounts are excluded. Needs a PO/TDD answer first.

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
