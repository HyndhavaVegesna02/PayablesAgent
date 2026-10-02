---
id: CHG-006
title: Owner web app — login, This week, Needs attention, confirm, approve, mark paid, options
type: feature
lane: sliced
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
Batch 3 plan, docs/batches/2026-10-03-3/plan.md (these replace the drafted ones).

- [ ] **AC1:** The owner plays through Part 1's worked example through the app's routes: confirm a bill, approve the plan, choose a shortfall option, mark a payment paid, and see the plan rerun to ₹3,83,000 after Nandi's credit. This is driven by `tests/test_phase5_exit.py` through the real routes and checked in a browser by the PO.
- [ ] **AC2:**
  - Login uses argon2 and a signed session cookie (HttpOnly, SameSite=Lax).
  - Every POST needs a valid CSRF token.
  - The role check runs server-side as a FastAPI dependency on every route.
  - A helper gets 403 on every owner-only route and sees only their own submissions on `/add`.
  - A table-driven test covers every route.
- [ ] **AC3:** Approving a plan that isn't current is refused (a run that isn't current, an inputs hash that changed, or a bill version that moved) and shows the current figures.
- [ ] **AC4:** AI-authored and document-sourced text renders as plain text everywhere: autoescape is on, there is no `|safe` or `Markup` (enforced by a test), and planted HTML renders escaped.
- [ ] **AC5:** The five screens and every route in the TDD's HTTP routes table except the three Gmail routes exist with their roles. Routes whose backend lands later (unlock, bank change, agent answers) refuse with 409 and a plain message. `/accounts` shows Gmail as "Not connected (set up later)".
- [ ] **AC6:** Settings changes and priority changes are recorded as events through the ledger writer and followed by a replan. Choosing a shortfall option records the choice and replans; split also performs the split.
- [ ] **AC7:** The seed creates a real demo login (owner and helper) from SEED_OWNER_PASSWORD and SEED_HELPER_PASSWORD, with dev defaults documented in `.env.example`. A blank SESSION_SECRET stops the web app with a message naming how to make one.
- [ ] **AC8:** The web layer never imports `app.ai`, enforced by import-linter. HTMX and Pico are served from `app/web/static/` with no CDN, and the layout is mobile-first (Pico's responsive container, a single column under 600px).

## Expected paths
- `app/web/`
- `app/main.py`
- `app/config.py`
- `app/ledger/writer.py`
- `app/domain/states.py`
- `fixtures/seed.py`
- `fixtures/test_inbox/07-credit-nandi-foods.eml`
- `tests/fake_ai.py`
- `.env.example`
- `pyproject.toml`
- `CLAUDE.md`
- `tests/web_helpers.py`
- `tests/test_web_auth.py`
- `tests/test_web_roles.py`
- `tests/test_web_week.py`
- `tests/test_web_attention.py`
- `tests/test_web_add.py`
- `tests/test_web_accounts_settings.py`
- `tests/test_web_api.py`
- `tests/test_web_plain_text.py`
- `tests/test_phase5_exit.py`
- `tests/test_seed.py`
- `tests/test_states.py`

## Open Questions
See the batch 3 plan's PO questions (each has a default).

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 5
- 2026-10-03: planned for batch 3 (lane sliced: five screens and about 20 routes can't be shown on one screen; cross-module). PO scope: login with argon2 and itsdangerous, CSRF on every POST, role dependency on every route, the TDD routes minus Gmail, stale-plan refusal, plain-text AI output, vendored HTMX and Pico, demo login, helper 403 matrix, web never imports ai.
