---
id: CHG-002
title: Ledger core — domain models, ledger writer, transition table, event triggers
type: feature
lane:
---

## Context
TDD Part 2, MVP build sequence, Phase 1. Owner: person B. Depends on CHG-001 (schema must exist).

## Description
`app/domain/models.py` (Pydantic models for every record), `app/domain/states.py`
(the allowed-transitions table from Part 2, "Ledger writer"), and
`app/ledger/writer.py` implementing `transition(entity, to_state, actor, reason,
source_ref)` — the only function that writes ledger tables or payable/receivable/
transaction state, bumping `version` and writing the `event` row in the same
transaction. Any actor starting with `agent:` must be refused for every transition.

## Acceptance Criteria
- [ ] AC1: A transition attempted by an `agent:*` actor is refused for every state in the table
- [ ] AC2: Every transition in Part 2's table succeeds for its allowed actor and is refused for any other
- [ ] AC3: A successful transition bumps `version` and writes exactly one `event` row in the same DB transaction
- [ ] AC4: Updating or deleting an `event` row raises (the triggers from CHG-001 are exercised here, not just created)

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 1
