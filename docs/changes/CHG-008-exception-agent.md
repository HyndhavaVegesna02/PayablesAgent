---
id: CHG-008
title: Exception agent — loop, tools, case file, escalation
type: feature
lane: sliced
---

## Context
TDD Part 2, MVP build sequence, Phase 7. Owner: person A. Depends on CHG-004, CHG-005.
Consumes the Gemini contract plus its own tool-call contract (structured `AgentStep`
output) — capped at lane `planned`. This is also the change the hackathon's
adversarial challenge (prompt injection) bears most directly on — see CHG-008's
eventual plan for the threat-model attack scenarios from Part 1, "Security and
threat model".

## Description
`app/agent/loop.py`, `tools.py`, `case_file.py`, `escalation.py` per Part 2,
"Agent loop". Five tools only (`search_gmail`, `get_ledger`, `run_planner`,
`add_candidate`, `ask_owner`); no tool approves a payment, marks a bill paid,
changes a rule, or sends anything outside the app.

## Acceptance Criteria
- [ ] AC1: An unknown-transaction scenario and a drift scenario each resolve or reach the owner within the step/thinking limits in Part 2
- [ ] AC2: A RESOLVED final answer is accepted only if every cited message ID came from this case's own searches and every candidate it relies on passed rule checks
- [ ] AC3: A case above the escalation amount starts at high thinking; one that hits the step or validation-failure limit at medium reruns at high before ever reaching the owner
- [ ] AC4: The hidden-instruction attack from Part 1 ("Attack to run and document") produces no change to priority, dates or payment status

## Expected paths
Batch 6 plan, docs/batches/2026-10-03-6/plan.md (slices S1-S8):
- `app/agent/` (cases, case_file, tools, loop, escalation, permissions)
- `app/ai/agent_step.py`, `app/ai/prompts/exception_agent.v1.md`, `app/ai/fixture_backend.py`
- `app/jobs/run_case.py`, `app/worker.py`
- `app/db/migrations/0003_agent_case_state.sql`, `app/db/read.py`
- `app/web/actions.py`, `app/web/repo.py`, `app/web/routes/attention.py`, `app/web/templates/attention.html`
- `fixtures/ai_replies.json`, `fixtures/test_inbox/11-debit-shree-transport-missed.eml`
- `docs/notes/agent-permissions.md`, `pyproject.toml`, `tests/`

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 7
- 2026-10-03: built in batch 6, slices S1-S8; D21 and deviations 1-7 PO-accepted
