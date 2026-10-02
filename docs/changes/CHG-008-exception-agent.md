---
id: CHG-008
title: Exception agent — loop, tools, case file, escalation
type: feature
lane:
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
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 7
