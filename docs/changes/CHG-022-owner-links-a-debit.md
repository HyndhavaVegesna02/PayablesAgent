---
id: CHG-022
title: The owner says which bill a debit paid (clears KL-1)
type: feature
lane:
---

## Context
Batch 3 review round 1, finding M1. PO decision D16 (2026-10-03): top priority for batch 4, alongside CHG-007.

The gap: the owner marks a bill PAID before its bank debit arrives. The debit then fails to match the bill, for one of three reasons:
- the payee name differs;
- the amount differs (for example, TDS was deducted);
- it arrived outside the matching window.

The debit stays UNMATCHED and lowers the balance, while the bill still counts as an outflow (D12). Cash is understated by the bill amount, and no owner action clears it. Batch 3 records this as known limit KL-1 and pins it with a test (tests/test_review_fixes_batch3.py::test_kl1_...).

The PO rejected auto-linking on a name mismatch. The name rule (TDD Part 2, "A new debit", step 4) is a security control: an exact-amount debit from an unrelated payee is what a fraudulent or mistaken debit looks like. The owner's mark-paid says "I paid this bill", not "this debit was that payment".

## Description
- **Where the owner acts:** in Needs attention, on an ambiguous_match or unknown_txn item for a debit, the owner picks the bill that debit paid.
- **What the writer does:**
  - moves the txn UNMATCHED → MATCHED, with the owner as actor (a new row in the transition table);
  - calls link_payment by the owner (today it is reconciler-only).

  This clears the double count. For a PAYMENT_EXPECTED or REVIEW bill, it moves the bill to PAID with matched_txn_id, which is the same outcome as the reconciler's match.
- **A name mismatch:** the action also offers "add this name as an alias" for the vendor. Only the owner can confirm it; that is the TDD's alias rule.
- **An amount difference (for example, TDS):** linked with the difference shown. The bill stays PAID, and the difference is recorded in the event.
- **Afterwards:** the case is closed by the owner, and the plan is replanned inline.

## Acceptance Criteria
<!-- to be written when planned -->
