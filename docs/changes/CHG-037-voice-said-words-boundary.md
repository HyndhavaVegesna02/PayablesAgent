---
id: CHG-037
title: The voice check's said-words match can accept a leading part of the amount
type: defect
lane:
---

## Context
Found in batch 10's review (a pre-existing gap, not introduced by D28). `app/validate/voice.py` checks that
the amount the model reports was said, by finding its words inside the transcript. The match is a substring
on word boundaries, so a leading part of a longer amount also matches: for a transcript saying "do lakh
pachaas hazaar ka bill", an amount_spoken of "do lakh" passes and becomes 2,00,000.

## Description
Require the matched span not to be followed by another number or scale word in the transcript, or compare
against every amount the transcript holds. A model that reports part of what was said must then go to the
owner, like any amount the code can't read.

## Acceptance Criteria
<!-- to be written when planned -->

## History
- 2026-10-04: drafted from batch 10's review
