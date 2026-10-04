---
id: CHG-045
title: Workflow A's new-decisions check finds the voice bill by amount and due date
type: defect
lane: direct
---

## Context
In the live rerun of workflow A (`docs/evals/workflow-A-2026-10-04-live.md`) the voice step read ₹1,50,000,
but `new-decisions` keyed the voice bill's plan line by the vendor name the model read, and the live reading
wasn't exactly "Sharma Packaging". The bill was in the ledger and planned: a harness-keying issue.

## Acceptance Criteria (PO)
- [ ] AC1: the check finds the bill with no invoice number by its amount and due date (₹1,50,000, Thu 5 Nov).
- [ ] AC2: the fixture workflow A report is regenerated; the live one stays as it was, and the README says the
  remaining live check was harness keying, fixed afterwards and not rerun live, to save spend.
- [ ] AC3: workflow B's ₹590 statement row read with no counterparty is a documented known limit (a true
  extraction miss) in the README and in CHG-025.

## History
- 2026-10-04: from the PO after the live AFTER; batch 16 (direct lane; no live spend)
