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

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 6
