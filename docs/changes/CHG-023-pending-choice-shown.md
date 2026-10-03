---
id: CHG-023
title: A chosen early_receipt still pending shows as chosen, not as a fresh option
type: chore
lane: direct
---

## Context
PO verdict on batch 3 (2026-10-03), a UX minor. After the clock moves (or any replan), the new run computes its shortfall options again. Needs attention then offers "Ask Nandi Foods to pay …" as an unchosen option, even though the owner chose it in an earlier run and the payment is still pending.

## Description
- A chosen early_receipt whose receivable is still open, and whose asked date has not passed, shows as "Chosen on Mon 12: waiting for Nandi's payment by Fri 16". It is not offered as a fresh choice.
- The same lookup D13 uses (chosen early_receipt options for the business) can drive it.
- Fold this into batch 4 only if it touches the same paths; otherwise it is a later chore.

## Acceptance Criteria
- [ ] **AC1:** After a replan (the clock moves, or a mail arrives), the chosen early_receipt shows as chosen and pending ("Chosen on Mon 12 Oct: waiting for Nandi Foods to pay ₹2,00,000 by Fri 16 Oct"), with no Choose button. After the asked date with no credit, it is offered again with "Asked by Fri 16 Oct; not received".

## Expected paths
- `app/ledger/reconcile.py`
- `app/web/repo.py`
- `app/web/routes/attention.py`
- `app/web/templates/attention.html`
- `tests/test_pending_early_receipt.py`
