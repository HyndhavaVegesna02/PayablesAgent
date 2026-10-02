---
id: CHG-006
title: Owner web app — login, This week, Needs attention, confirm, approve, mark paid, options
type: feature
lane:
---

## Context
TDD Part 2, MVP build sequence, Phase 5. Owner: person B. Depends on CHG-002, CHG-003.
No external contract here (routes and templates are ours), but the surface is
genuinely cross-module (auth, ledger writes, planner reads, templates) — candidate
for lane `sliced`, built as vertical slices per screen rather than by stack layer.

## Description
FastAPI routes + Jinja/HTMX templates for the five screens in Part 1 ("Owner web
app") and the HTTP routes table in Part 2. Role checked by a FastAPI dependency on
every route; CSRF on every POST; stale-plan approvals refused.

## Acceptance Criteria
- [ ] AC1: The owner can play through Part 1's worked example in the browser end to end: confirm a bill, approve the plan, choose a shortfall option, mark a payment paid
- [ ] AC2: A helper account can submit but cannot confirm, approve, mark paid, or see anything but their own submissions
- [ ] AC3: Approving a plan whose `version` has moved on is refused and shows the current figures
- [ ] AC4: AI-authored text renders as plain text everywhere (no Markdown/HTML interpretation)

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
<!-- none yet -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 5
