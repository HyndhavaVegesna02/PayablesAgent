---
id: CHG-025
title: Batch 5 review notes not fixed in the batch
type: chore
lane:
---

## Context
These are the non-blocking notes from the batch 5 review (docs/batches/2026-10-03-5/review.md, rounds 1-4). PO policy: non-blocking notes become backlog chores.

## Description
- **Voice amount check:**
  - The transcript match joins a decimal point between digits, so an amount_spoken of "15 lakh" matches "1.5 lakh". It should join only commas.
  - A word-level suffix ("pachaas hazaar" inside "ek lakh pachaas hazaar") still matches.
  - The owner confirms every voice bill with the transcript beside it.
- **Voice amounts with no scale:** a lone "45" or "ek" reads as ₹45 or ₹1.
- **Round-off cap:** a round-off the model files under `lines` sidesteps the D19 ₹1.00 cap, and the retry note hands the model the exact shortfall. Both rely on honest labelling.
- **Statement sender:** a statement that arrives by email must come from an account's alert sender. A separate e-statement address fails the account check and isn't polled.
- **Two passwords in one email:** an email with two locked PDFs under different passwords can't be unlocked (one password is tried on both).
- **IFSC-only bank change:** approving a proposal that printed only an IFSC keeps the old account and the new IFSC as "verified".
- **Typed duplicates without a number:** a typed bill with no invoice number, from the same vendor, for the same amount, on the same date as a recorded one is now refused, with no override. This matches the pipeline's rule.
- **Live check of the prompts:** the multimodal prompts (sort.v2, extract_invoice, extract_statement, extract_voice) are unproven on real Gemini. Run at most 3 authorised smoke calls when the PO allows (Q7).

- **A statement row read with no counterparty (live, 2026-10-04):** in both live runs of workflow B, Gemini read
  the bank statement's ₹590 bank-charges row ("SMS AND ACCOUNT CHARGES") with no counterparty. The amount and
  date are right, so the debit is counted and its question is found by amount (CHG-043); the missing name is a
  true extraction miss, visible in `docs/evals/workflow-B-2026-10-04-live.md` (`rows-in-the-ledger-once`).
  A fix would be prompt work on extract_statement, measured live.

## Acceptance Criteria
<!-- to be written when planned -->

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
