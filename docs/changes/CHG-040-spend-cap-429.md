---
id: CHG-040
title: A 429 for Gemini's spending cap is permanent, and the eval guard stops at once on it
type: defect
lane: direct
---

## Context
Phase 2's live run stopped on 429s that were read as rate limits and backed off five times. A live ping
showed the cause: 429 RESOURCE_EXHAUSTED "Your project has exceeded its monthly spending cap". Waiting can't
help with that; only the owner of the Google project can raise the cap.

## Acceptance Criteria
- [ ] AC1: `app/ai/client.py`: a 429 whose message names a spending cap or prepayment ("spending cap", "spend
  cap", "prepayment credits"), or whose ErrorInfo reason names spending, billing or prepayment, is permanent
  (retryable False), like a 402. A rate-limit 429 stays retryable.
- [ ] AC2: `evals/budget.py`: the guard does not back off on a permanent 429. It stops the invocation at once,
  and `stopped_because` names the spend cap.
- [ ] AC3: both kinds of 429 are tested through GeminiBackend with httpx.MockTransport, and through the guard.

## History
- 2026-10-04: from the PO, after a live ping showed the monthly spending cap; batch 13 (direct lane)
