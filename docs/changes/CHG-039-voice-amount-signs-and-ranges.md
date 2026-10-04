---
id: CHG-039
title: The voice amount reader counts bare 5+ digits as money (D30) and treats a Unicode minus, a rupee-word sign and range punctuation like their plain forms
type: defect
lane: direct
---

## Context
Batch 11's verdict (PO D30) and its round-5 minors. The voice amount check is done after this change: one
review round, and further spelling edge cases go to the backlog as known limits.
- D29 rule 1 counted only formatted digits as money, so "Bill 150000 ka, advance 50,000 diya" passed the
  advance. D30: a bare run of five or more digits is money (five, so a year such as 2026 is not).
- A Unicode minus ("Bill −1,50,000 ka") was split off as a mark, so the digits read as positive.
- `parse_spoken_inr("rupees -5")` was 500: the sign check stripped ₹, Rs and INR but not a rupee word.
- Spaced range punctuation ("25 / 30 lakh", "25 -- 30 lakh", "25 & 30 lakh") passed the upper bound.
Each fix can only add flags.

## Acceptance Criteria
- [ ] AC1 (D30): a bare run of five or more digits is money-shaped; four or fewer (a year) is not. "Bill
  150000 ka, advance 50,000 diya" flags as two amounts; "invoice 418277" next to an amount is a known false flag.
- [ ] AC2: a Unicode minus is read as a minus: "−1,50,000" is refused as negative.
- [ ] AC3: parse_spoken_inr refuses a negative amount after any leading currency word or sign ("rupees -5",
  "Rs.-5", "₹ -5").
- [ ] AC4: a spaced "/", "--" or "&" between numbers is a range: the amount is None.
- [ ] AC5: the README's known limits say, in one short paragraph, what the voice check can't tell by form
  (D30 items 1-5) and that the owner confirms every voice bill with the transcript beside it.

## History
- 2026-10-04: drafted from batch 11's review, round 5
- 2026-10-04: PO D30 added the bare-digits rule; planned for batch 12 (direct lane, one review round)
