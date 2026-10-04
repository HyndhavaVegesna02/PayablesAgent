---
id: CHG-039
title: The voice amount reader treats a Unicode minus, a rupee-word sign and range punctuation like their plain forms
type: defect
lane:
---

## Context
Batch 11's round-5 review (minors, after APPROVE). `app/domain/money.py::money_said`:
- a Unicode minus ("Bill −1,50,000 ka") is tokenized as a mark, so the digits read as positive and pass;
- `parse_spoken_inr("rupees -5")` is 500, because its sign check strips ₹, Rs and INR but not a rupee word;
- range punctuation the dash rule doesn't cover ("25 / 30 lakh", "25 -- 30 lakh", "25 & 30 lakh") passes the
  upper bound.
All are unlikely in a voice transcript, and each fix can only add flags.

## Acceptance Criteria
<!-- to be written when planned -->

## History
- 2026-10-04: drafted from batch 11's review, round 5
