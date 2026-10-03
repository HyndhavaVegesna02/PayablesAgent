---
id: CHG-028
title: Statutory debits never match on their own
type: defect
lane: planned
---

## Context
Found by the full-workflow runs (CHG-027, plan addendum W3).

## Description
A statutory payable (PF and ESI, GST, TDS) has no party, so `match_debit` can't name-match its challan debit ("EPFO ESIC CHALLAN", "GST CHALLAN CBIC"). Every statutory payment therefore goes to REVIEW, opens an ambiguous_match case, raises an unexpected_debit alert, and asks the owner "which bill did it pay?". The owner can link it, and both workflow runs do. But a routine, approved, statutory payment shouldn't need the owner each time.

Possible fix: match a statutory bill by its tax type, through a short list of challan payee names per tax type kept in config (EPFO/ESIC for PF and ESI, CBIC/GSTN for GST), or by the challan reference once the challan document is linked (`tax_obligation.challan_document_id`).

## Acceptance Criteria
Batch 8 plan, docs/batches/2026-10-04-8/plan.md (PO decision D27, 2026-10-04):
- [ ] AC1: config.yaml `matching.statutory_payees` lists payee keywords per tax_type (PF: EPFO; ESI: ESIC; GST: GST, CBIC, GSTN; TDS and ADVANCE_TAX: CBDT, ITD, TIN-NSDL, OLTAS), checked at startup.
- [ ] AC2: a debit naming a keyword of a statutory bill's tax types, with the same amount in the matching window, is MATCHED by the reconciler and the bill is PAID.
- [ ] AC3: more than one such bill goes to REVIEW, as now; a debit with no keyword stays a case; the owner's link stays as the fallback.
- [ ] AC4: workflow A step 11 expects PF and ESI PAID with no owner action; the owner's link is still checked on a debit that names no keyword.

## History
- 2026-10-04: PO decision D27: build now; planned for batch 8
- 2026-10-03: drafted from CHG-027's runs
