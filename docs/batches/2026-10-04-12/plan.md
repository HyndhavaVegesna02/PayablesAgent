# Batch 12: plan (PO D30; the voice amount check closes)

**Branch:** `batch-12`, cut from main at 2a889a2. One direct-lane change, CHG-039: it is in one module and its
tests, and shows in one command. One review round (PO): further spelling edge cases go to the backlog as
known limits, not fix rounds.

- `_money_shaped`: a bare run of five or more digits is money (D30).
- `money_said`: a Unicode minus is a minus; a spaced "/", "--" or "&" between numbers is a range.
- `parse_spoken_inr`: the sign check skips any leading currency word or sign.
- README, known limits: one short paragraph on what the voice check can't tell by form (D30 items 1-5).

No live calls.
