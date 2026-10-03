---
id: CHG-022
title: The owner says which bill a debit paid (clears KL-1)
type: feature
lane: planned
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
Batch 4 plan, docs/batches/2026-10-03-4/plan.md (PO approved; Q1-Q4 defaults).
- [ ] **AC1:** For a debit that did not auto-match, the owner picks the bill on Needs attention. The debit becomes MATCHED and the bill PAID and linked, with owner:1 events, and the plan subtracts the money once. The KL-1 test now passes in its "cleared" form.
- [ ] **AC2:** An amount difference (for example, TDS) is linked, and the difference is recorded in the event reason. The bill keeps its own amount.
- [ ] **AC3:** "Add as a name" is owner-only and off by default. With it ticked, the next debit with that payee name auto-matches. Without it, nothing about the vendor changes.
- [ ] **AC4:** The other REVIEW bills held for that debit return to PAYMENT_EXPECTED, and the case closes as CLOSED_BY_OWNER.
- [ ] **AC5:** "Not a bill payment" closes the case and leaves the debit UNMATCHED and counted.
- [ ] **AC6:** Every action goes through the writer, in one transaction with the replan. A refusal writes nothing.

## Expected paths
- `app/domain/states.py`
- `app/ledger/writer.py`
- `app/ledger/reconcile.py`
- `app/web/actions.py`
- `app/web/repo.py`
- `app/web/routes/attention.py`
- `app/web/templates/attention.html`
- `tests/test_owner_explains_debit.py`
- `tests/test_states.py`
- `tests/test_ledger_transitions.py`
- `tests/test_reconcile_owner_paid.py`
- `tests/test_web_attention.py`
- `tests/test_review_fixes_batch3.py`

## Notes
- The plan gave `link_payment` an optional `difference_paise`. Instead, the caller writes the difference into the event reason, which is the same record with less plumbing.
