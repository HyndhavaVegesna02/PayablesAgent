---
id: CHG-020
title: AIUnavailable and its trace step carry the SDK's error message, redacted
type: defect
lane: direct
---

## Context
Found by the batch 2 smoke run (403 PERMISSION_DENIED). AIUnavailable kept only the HTTP code and status, so the reason Google gave (API not enabled, key restricted, no model access) was lost from the error, the job's last_error and the trace. PO, 2026-10-03: the first item of batch 3, lane direct.

## Description
- AIUnavailable and the trace step for an outage carry the SDK's error message.
- The message goes through redaction. A test proves the key never appears, even if the SDK message echoes it.
- The classification is unchanged: 403 (and other 4xx except 429) is permanent; 429, 5xx and transport errors are retryable.

## Acceptance Criteria
- [ ] AC1: A refused request's AIUnavailable message, job last_error and trace step include the SDK's own message text.
- [ ] AC2: An SDK message that contains the API key (or any value shaped like a Google API key) is redacted in all three places.
- [ ] AC3: The retryable/permanent mapping is unchanged (existing tests still drive 429, 500, 503, 400, 403, code None, timeouts).

## Expected paths
- `app/ai/client.py`
- `app/trace/tracer.py`
- `tests/test_ai_client.py`

## Open Questions
<!-- none -->

## History
- 2026-10-03: drafted at PO request after the batch 2 smoke run
