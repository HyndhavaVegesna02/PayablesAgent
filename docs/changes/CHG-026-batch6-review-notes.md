---
id: CHG-026
title: Batch 6 review notes not fixed in the batch
type: chore
lane:
---

## Context
The non-blocking notes from the batch 6 review (docs/batches/2026-10-03-6/review.md). PO policy: non-blocking notes become backlog chores.

## Description
- **A drift case can still stick at CHECKING after a worker crash.** If the worker crashes on a run_case job's last attempt, the stale-lock reclaim marks the job dead without its handler running, so `_give_up` never hands the case to the owner. Fix: a reaper for dead run_case jobs, or have the 23:00 recheck move a CHECKING account with no live run to ASK_OWNER with confirm_balance.
- **Relative phrasing in plan notes:** "next week" and "₹10,000 more than before" pass check_summary. The amount itself must still be in the diff, so the risk is low. Consider adding relative time words.
- **Over-strict sign reading:** "₹1,83,000-₹20,000" reads the second amount as negative. That is safe, since it falls back to the template, but a note can fail for punctuation.
- **A transient AI outage gives the template at once,** with no retry for the plan note. This is the plan's choice; revisit if template notes are common.

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-03: drafted from the batch 6 review
