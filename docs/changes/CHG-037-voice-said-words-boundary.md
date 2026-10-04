---
id: CHG-037
title: The voice amount check compares parsed paise, never a text substring
type: defect
lane: direct
---

## Context
Found in batch 10's review (a pre-existing gap, not introduced by D28). `app/validate/voice.py` checks that
the amount the model reports was said, by finding its words inside the transcript. The match is a substring
on word boundaries, so a leading part of a longer amount also matches: for a transcript saying "do lakh
pachaas hazaar ka bill", an amount_spoken of "do lakh" passes and becomes 2,00,000. The PO's batch 10 verdict
calls this a correctness bug in the one place the model's words must decide nothing on their own.

## Description (PO, batch 10 verdict)
Compare the paise parsed from amount_spoken against the paise parsed from the amounts the transcript says.
Pass only on exact equality of those numbers, never on a text match. If no amount can be parsed from the
transcript, the check fails and the owner types the amount; it never passes.

## PO D29 (batch 11, review round 1)
The review showed that "equals one of the transcript's amounts" lets the model choose among them (a date, an
invoice number, an advance). The PO ruled:
1. only money-shaped amounts count: a scale word, a currency word after it, Rs or ₹ before it, or digits
   grouped with commas;
2. more than one DISTINCT money-shaped amount in the transcript flags the bill; the same amount said twice is
   one;
3. the bill passes only when the paise exactly equal that single amount.
Extra false flags are the right trade: a flag costs the owner seconds, a wrong amount costs money.

## Acceptance Criteria
- [ ] AC1: `app/domain/money.py::money_said(transcript)` returns every money-shaped amount the transcript says.
  The transcript is cut into clusters of number words, and each cluster is read whole or not at all, never
  a leading part of it. Number words the parser doesn't read (Hindi 11-99 spellings, sava, laakh, minus,
  paise, hyphenated numbers) still belong to a cluster, so it reads as None (an amount code can't read).
  A currency word after an amount, or a sentence end, closes it, and a number word straight after that makes
  it None. A comma neither closes an amount nor, after a rupee word, carries it on. Digit groups
  ("1,50,000") and decimals ("1.5 lakh") stay whole. An amount written as one token ("Rs1,50,000/-",
  "1.5L"), a hyphenated amount ("dedh-lakh"), a number straight after digits ("Rs 1,00,000 pachaas"), and a
  range or guess ("25 - 30 lakh", "lagbhag do lakh", "ek lakh plus GST") are read whole or are None.
- [ ] AC2 (D29): the voice check passes only when the transcript's money-shaped amounts are exactly one
  distinct amount and parse_spoken_inr(amount_spoken) equals it, as integer paise. Every case from the
  review is a table test. Table tests where the words are a substring of what was said but the amounts differ
  ("dedh lakh" in "dedh lakh pachaas hazaar", "do lakh" in "do lakh pachaas hazaar", "bees hazaar" in "bees
  hazaar paanch sau") fail the check, and the bill goes to the owner with the amount empty.
- [ ] AC3: a transcript with no amount the parser reads fails the check (the owner types it), never passes.
- [ ] AC4: the same amount said in other words passes ("1,50,000" for "ek lakh pachaas hazaar"), and so does
  one amount said twice; the existing voice tests and D28's cut-short currency word still pass.

## History
- 2026-10-04: drafted from batch 10's review
- 2026-10-04: specified by the PO in the batch 10 verdict; planned for batch 11 (direct lane)
- 2026-10-04: batch 11 review round 1: a refused run read as its leading part (critical); membership among
  all the transcript's numbers (major) -> PO D29
- 2026-10-04: batch 11 review round 2: the leading part still passed through number words the parser lacks,
  and through a tail after the unit or a full stop (critical) -> whole-cluster reading
- 2026-10-04: batch 11 review round 3: amounts written with marks, a number after digits, and hyphenated
  amounts were dropped or read in part (critical) -> fixed; ranges and guesses are None
