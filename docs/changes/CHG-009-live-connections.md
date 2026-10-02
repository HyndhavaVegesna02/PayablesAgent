---
id: CHG-009
title: Live connections — Gmail OAuth, GmailSource, SMTP alerts
type: feature
lane:
---

## Context
TDD Part 2, MVP build sequence, Phase 8. Owner: person A. Depends on CHG-004.
Consumes an external interface this repo doesn't own (Gmail API OAuth, scope and
token-refusal semantics) — capped at lane `planned`.

## Description
`app/ingest/gmail.py`, `gmail_oauth.py`, `app/notify/smtp.py` per Part 2, "Gmail
ingestion". Read-only `gmail.readonly` scope only; refuse the connection if the
granted scope is anything else; handle `invalid_grant` by disconnecting and opening
a `reconnect_gmail` owner question.

## Acceptance Criteria
- [ ] AC1: Synthetic emails sent to a test Gmail account flow end to end into the ledger
- [ ] AC2: Revoking access produces a `reconnect_gmail` Needs-attention item, and the planner keeps running on existing data
- [ ] AC3: A connection request for any scope other than `gmail.readonly` is refused
- [ ] AC4: The access token is never written anywhere; only the Fernet-encrypted refresh token is stored

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 8
