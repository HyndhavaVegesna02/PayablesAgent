---
id: CHG-029
title: A vendor's first bank details are recorded without a flag
type: defect
lane: planned
---

## Context
Found in the batch 7 review (evidence docs, B1): the demo walkthrough relied on a bank-change flag that only fires when the vendor already has details on record.

## Description
`app/ingest/pipeline.py::_check_bank_details` returns early for a vendor with no bank details on record. The first bill the owner confirms for a vendor sets its details, with no flag. In the seeded demo every party starts with none. So a fake invoice for a real vendor (fixture 09, AP/2610/140), confirmed before any real one, would record the attacker's account as the vendor's.

The owner still confirms that bill by hand, and the entry shows its bank details. A fix is a product decision for the PO. Options: ask the owner to verify a vendor's first bank details the same way as a change (approve_bank_change), or show them more prominently on the entry.

## Acceptance Criteria
Batch 8 plan, docs/batches/2026-10-04-8/plan.md (PO decision D26, 2026-10-04):
- [ ] AC1: bank details read from any document for a vendor with none on record make the vendor change_pending with an approve_bank_change question; nothing is stored until the owner approves.
- [ ] AC2: a fake first invoice confirmed before any real one can't set an account without an explicit approve_bank_change.
- [ ] AC3: until approved, the bill shows the D20 warning and approving its payment needs the tick.
- [ ] AC4: reject leaves the vendor with no details; approve stores them as verified; owner only.
- [ ] AC5: workflow B checks AC2; the README and threat model no longer list the limit.

## History
- 2026-10-04: PO decision D26: build now as a security fix; planned for batch 8
- 2026-10-03: drafted from the batch 7 review
