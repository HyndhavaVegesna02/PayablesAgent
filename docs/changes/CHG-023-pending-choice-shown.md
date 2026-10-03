---
id: CHG-023
title: A chosen early_receipt still pending shows as chosen, not as a fresh option
type: chore
lane:
---

## Context
PO verdict on batch 3 (2026-10-03), a UX minor. After the clock moves (or any replan), the new run computes its shortfall options again. Needs attention then offers "Ask Nandi Foods to pay …" as an unchosen option, even though the owner chose it in an earlier run and the payment is still pending.

## Description
- A chosen early_receipt whose receivable is still open, and whose asked date has not passed, shows as "Chosen on Mon 12: waiting for Nandi's payment by Fri 16". It is not offered as a fresh choice.
- The same lookup D13 uses (chosen early_receipt options for the business) can drive it.
- Fold this into batch 4 only if it touches the same paths; otherwise it is a later chore.

## Acceptance Criteria
<!-- to be written when planned -->
