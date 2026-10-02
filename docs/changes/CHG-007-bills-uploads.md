---
id: CHG-007
title: Bills and uploads — invoices by email, photos, PDF unlock, voice notes, all rule checks
type: feature
lane:
---

## Context
TDD Part 2, MVP build sequence, Phase 6. Owner: person A. Depends on CHG-004.
Consumes the Gemini contract (image/audio/PDF extraction) — capped at lane `planned`.

## Description
Extend the pipeline to photos, PDFs (PyMuPDF unlock), and voice notes
(transcript + structured candidate in one call), plus duplicate detection across
sources (same invoice by email and by photo → one payable, not two).

## Acceptance Criteria
- [ ] AC1: A password-protected statement PDF unlocks with a once-used, never-stored password and passes statement arithmetic
- [ ] AC2: A handwritten bill photo extracts fields that pass GSTIN and total checks
- [ ] AC3: A Hinglish voice note saying "dedh lakh" extracts ₹1,50,000 and shows the transcript beside it
- [ ] AC4: The same invoice arriving by email and by photo produces one payable, not two

## Expected paths
<!-- fill in when pulled into a batch -->

## PO decisions
- D11 (2026-10-02, batch 1 verdict): MISSING tax amounts.
  - A MISSING obligation is stored with payable_id NULL and no payable. Opening it raises a `ca_reminder` owner question.
  - build_snapshot surfaces MISSING statutory obligations due inside the horizon as a plan warning, e.g. "GST Oct amount missing: plan may be optimistic". The planner never invents an amount.
  - When the owner or CA supplies the amount, the obligation moves to CONFIRMED or ESTIMATED. That creates its statutory payable through the writer, and a replan follows.
  - Until CHG-007 lands, `create_tax_obligation` refuses MISSING (batch 1).

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 6
