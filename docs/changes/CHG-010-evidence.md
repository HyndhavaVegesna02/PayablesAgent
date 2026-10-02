---
id: CHG-010
title: Evidence — scenario runs, harness comparison, attack, two traces, demo video
type: feature
lane:
---

## Context
TDD Part 2, MVP build sequence, Phase 9 (final). Owner: both. Depends on all prior
phases. This change produces the hackathon's required deliverables, not new product
code — it is still routed through YourTeam because it touches `evals/` and the
Makefile's `evals`/`ablation` targets.

## Description
`evals/runner.py` (5 runs per scenario, success rate/spread/worst case), the
scenario suite from Part 1 ("Evaluation"), `evals/ablation.py` (Gemini fixed, bare
loop vs. full harness, per-component delta), the documented attack from Part 1
("Attack to run and document"), one success trace, one failure trace, and the
one-page threat model.

## Acceptance Criteria
- [ ] AC1: Every scenario in Part 1's scenario-suite table runs 5 times; the report gives success rate, spread and worst case per scenario
- [ ] AC2: `make ablation` reports the delta between the bare loop and the full harness on the same model, and names which single component bought the most
- [ ] AC3: Both planted attacks (vendor bank-detail change, hidden instruction in a vendor email) are run and their outcomes documented
- [ ] AC4: One success trace and one failure trace are captured and are readable via `python -m app.trace.view`
- [ ] AC5: The threat model is one page and includes the lethal-trifecta analysis from Part 1 ("The three risky ingredients")

## Expected paths
<!-- fill in when pulled into a batch -->

## Open Questions
- Are 6 steps and the ₹50,000 default escalation amount the right starting points? (Part 1's own open question — revisit once the first eval runs are in.)

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 9
