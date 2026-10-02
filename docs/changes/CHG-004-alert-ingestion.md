---
id: CHG-004
title: Alert ingestion — MailSource, test inbox, ai.client, sort/extract/validate for bank alerts
type: feature
lane: planned
---

## Context
TDD Part 2, MVP build sequence, Phase 3. Owner: person A. Depends on CHG-001 (schema, trace).
Consumes a contract this repo doesn't write — the Gemini structured-output API — so this
change is capped at lane `planned` regardless of how it's sliced; see SKILL.md's router.

## Description
`app/ingest/mail_source.py` (the `MailSource` protocol), `app/ingest/eml_folder.py`
(test inbox), `app/ai/client.py` (the one function that calls Gemini), `app/ai/sort.py`,
`app/ai/extract.py`, and the GSTIN/invoice/statement/dates/duplicates validators.

## Acceptance Criteria
Batch 2 plan, docs/batches/2026-10-02-2/plan.md (these replace the drafted ones).

- [ ] AC1: A sample HDFC-style debit alert in the test inbox becomes a `bank_txn` row end to end through the worker: poll → source_document → sort → extract → validate → `writer.create_bank_txn` → `reconcile_txn` queued. The fake AI returns canned responses.
- [ ] AC2: The run leaves a readable trace. `python -m app.trace.view job-<id>-attempt-1` shows the sort and extract calls with model, thinking level, tokens and cost, plus the validation result. Fields named `tokens` are not redacted.
- [ ] AC3: Extraction uses structured output with `response_json_schema` from the Pydantic model, and our code parses `r.text`. An offline MockTransport test asserts the outgoing request carries `thinkingLevel`, the JSON schema, and no temperature or thinking budget.
- [ ] AC4: Every alert candidate records every Part 1 rule check in `checks_json`, with GSTIN, invoice and statement marked `not_applicable` (Q3). A failed check triggers one re-extract with the failures attached. A second failure escalates to high thinking, and a third leaves the candidate `AWAITING_OWNER` with a `confirm_record` question.
- [ ] AC5: A duplicate alert (same dedup_key), or one from an unknown sender or account, never reaches the ledger.
- [ ] AC6: An irrelevant email stops after sort (IRRELEVANT). A failure or return email queues `reconcile_failure`.
- [ ] AC7: SDK errors map to retryable or permanent as in the contract grid. Offline tests cover 429, 500, 400 and timeout.
- [ ] AC8: No test makes a network connection; an autouse guard blocks non-loopback connects. `make smoke-gemini` exists, makes at most 3 live calls, and is not run in this batch.
- [ ] AC9: `app.ai.client` is the only module that imports `google.genai`. This is enforced by an import-linter contract, and `app.ai` still never imports ledger, db or web.

## Expected paths
- `app/ingest/mail_source.py`
- `app/ingest/eml_folder.py`
- `app/ingest/store.py`
- `app/ingest/pipeline.py`
- `app/ai/client.py`
- `app/ai/sort.py`
- `app/ai/extract.py`
- `app/ai/prompts/`
- `app/ai/smoke.py`
- `app/validate/`
- `app/domain/money.py`
- `app/trace/tracer.py`
- `app/config.py`
- `config.yaml`
- `fixtures/seed.py`
- `fixtures/test_inbox/`
- `Makefile`
- `pyproject.toml`
- `tests/conftest.py`
- `tests/fake_ai.py`
- `tests/test_ai_client.py`
- `tests/test_eml_folder.py`
- `tests/test_pipeline.py`
- `tests/test_validate_alert.py`
- `tests/test_money.py`
- `tests/test_tracer.py`

## Open Questions
See the batch 2 plan's PO questions (each has a default).

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 3
- 2026-10-02: planned for batch 2 (lane planned, cap: Gemini SDK and RFC 2822). ACs rewritten in the plan: scoped to bank alerts and failure notices; GSTIN, invoice and statement checks recorded not_applicable and built in CHG-007 (Q3); amounts come back as text and code parses them (Q4).
