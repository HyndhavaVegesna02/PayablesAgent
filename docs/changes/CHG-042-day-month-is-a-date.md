---
id: CHG-042
title: A day number next to a month name is a date, not money
type: defect
lane: direct
---

## Context
Live phase 2 (`docs/evals/2026-10-04-live-baseline-part2/`): every run of scenario 04 sent the bill to the
owner. Gemini writes the note as "Sharma Packaging ke bill dedh lakh rupaye 5 November tak dena hai", with no
comma after the unit. Batch 11's rule (CHG-037: a number straight after the rupee word is more of the amount)
read the due date's 5 as part of the amount, so `money_said` gave None. The TDD's own example regressed; the
direction is safe (the owner types it), but wrong.

## Acceptance Criteria (PO)
- [ ] AC1: a day number (digits 1-31, "5th", or a number word up to 31) right before a month name ("November",
  "Nov") or "tarikh" is a date: it ends any amount, is never part of one, and isn't counted as money.
- [ ] AC2: the live transcript and the canonical sentence's natural forms pass with ₹1,50,000.
- [ ] AC3: D29 holds: exactly one distinct money-shaped amount, exact paise; "pachaas hazaar paanch November"
  gives exactly one amount (₹50,000); a number above 31 before a month ("ek lakh pachaas November") is still
  more of the amount, and every earlier flagged row still flags.

## History
- 2026-10-04: from the live phase 2 run and the PO; batch 15 (direct lane)
