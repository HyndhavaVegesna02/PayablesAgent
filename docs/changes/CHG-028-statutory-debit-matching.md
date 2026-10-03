---
id: CHG-028
title: Statutory debits never match on their own
type: defect
lane:
---

## Context
Found by the full-workflow runs (CHG-027, plan addendum W3).

## Description
A statutory payable (PF and ESI, GST, TDS) has no party, so `match_debit` can't name-match its challan debit ("EPFO ESIC CHALLAN", "GST CHALLAN CBIC"). Every statutory payment therefore goes to REVIEW, opens an ambiguous_match case, raises an unexpected_debit alert, and asks the owner "which bill did it pay?". The owner can link it, and both workflow runs do. But a routine, approved, statutory payment shouldn't need the owner each time.

Possible fix: match a statutory bill by its tax type, through a short list of challan payee names per tax type kept in config (EPFO/ESIC for PF and ESI, CBIC/GSTN for GST), or by the challan reference once the challan document is linked (`tax_obligation.challan_document_id`).

## Acceptance Criteria
<!-- to be written when planned -->

## History
- 2026-10-03: drafted from CHG-027's runs
