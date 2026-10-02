---
id: CHG-004
title: Alert ingestion — MailSource, test inbox, ai.client, sort/extract/validate for bank alerts
type: feature
lane:
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
- [ ] AC1: A sample bank-alert `.eml` becomes a `bank_txn` row, end to end through sort → extract → validate → ledger
- [ ] AC2: A readable trace exists for that run (`python -m app.trace.view <run_id>`)
- [ ] AC3: Extraction uses structured output with a JSON schema generated from the Pydantic model
- [ ] AC4: Every rule check in Part 1 ("Rule checks") runs on every candidate and is recorded in `candidate.checks_json`

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 3
