---
id: CHG-030
title: A missing due date reaches the owner flagged, never as a value the form refuses
type: defect
lane: planned
---

## Context
Found by the first live run (`docs/evals/2026-10-04-live-pilot/`, scenario 04) and diagnosed from its kept trace. The speaker said "5 November" with no year, and Gemini returned no due date, as the voice prompt says to. The voice checks then marked `dates` as not applicable and routed the bill as "all checks passed". The owner's form therefore got an empty required field with no flag. The scripted owner confirmed it, the form refused it, and the eval scored that as a crash.

## Description
The fault is in the product and the eval, not the model. TDD pipeline step 5: the owner fills the fields that still fail. A field the model couldn't give must reach the owner as a flagged empty field, never as a passing entry that the form then refuses.

## Acceptance Criteria
Batch 8 plan, docs/batches/2026-10-04-8/plan.md:
- [ ] AC1: a bill read from any document with no due date fails a `dates` check that names the field. It goes to the owner as AWAITING_OWNER with the field flagged, after one attempt, since asking again can't supply what wasn't said.
- [ ] AC2: the voice prompt says to leave the date empty when no full date was said and never to guess a year. The fix is general, not tuned to one clip.
- [ ] AC3: in an eval, a form refusal of an extracted value is scored as a component failure of `extract`, with the form's message. Real exceptions stay crashes.
- [ ] AC4: scenario 04's scripted owner fills only the fields the entry flags, and a check asserts that the due date was flagged.

## History
- 2026-10-04: found by the live pilot; PO folded it into batch 8
