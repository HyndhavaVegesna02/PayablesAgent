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

- [ ] **AC1:** The owner plays through Part 1's worked example through the app's routes: confirm a bill, approve the plan, choose a shortfall option, mark a payment paid, and see the plan rerun to ₹3,83,000 after Nandi's credit. This is driven by `tests/test_phase5_exit.py` through the real routes and checked in a browser by the PO. The walkthrough's audit trail has an event for every owner action, with actor owner:1 (PO addition).
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
- [ ] **AC9 (PO decision D12, 2026-10-03):** An owner-PAID bill whose bank debit has not arrived stays a committed outflow in the plan (build_snapshot passes it to the planner as PAYMENT_EXPECTED, on its planned date or today), so marking paid never overstates cash. When the debit arrives, match_debit treats a PAID-unmatched bill as a candidate on the same terms as an approved one. A single match sets the txn MATCHED and calls `writer.link_payment` (reconciler only; sets matched_txn_id, bumps the version, writes PAYABLE_PAYMENT_LINKED, makes no state change, and refuses if already linked). The bill then leaves the snapshot, so the money is subtracted once. More than one candidate means REVIEW (for the approved ones) and a case, as before. Marking a REVIEW bill paid links the debit it was held for. Known limit (recorded, not built): if that debit never arrives, the outflow stays committed until the next statement's drift check shows it.

## PO decisions during the build
- **D13 (2026-10-03, dev choice reported to the PO):** choosing early_receipt changes no ledger row (Q1), so match_credit also accepts a credit within the matching window of the to_date of a *chosen* early_receipt option for that receivable (same name and amount rules). Without it Nandi's Fri 16 credit, 12 days before its expected date, would be an ambiguous case, not CONFIRMED.
- **Inputs hash (dev choice reported to the PO):** plan_run.inputs_sha256 covers what the planner reads, leaving out a bill's planner-owned status and planned date (except PAYMENT_EXPECTED), so the run's own moves don't make every approval stale (Q3).
- **D14 (2026-10-03, PO):** demo mode has ONE clock. With DEMO_NOW set, the web app, the worker and `make seed` read a DemoClock whose instant lives in DATA_DIR/demo_clock.txt (starting at DEMO_NOW). It stands still and moves only forward, by `make demo-time T=...` or the owner-only POST /demo/time (registered only in demo mode; a form on Settings). Crossing a Monday 07:00 enqueues that Monday's plan (the demo worker has no real-time Monday cron); every move queues one mail poll. `make reseed` restarts the clock. DEMO_NOW blank: SystemClock, no demo route. `make seed` also makes the first plan.
- **D15 (2026-10-03, PO):** DEMO_AI=fixtures (only with DEMO_NOW) makes the worker answer from the canned replies in fixtures/test_inbox/ai_replies.json (one copy, shared with tests/fake_ai.py), matched by the email text. Recorded as model fixture-ai with zero tokens and cost; the app shows "AI replies are canned fixtures". An email with no canned reply is a permanent AIUnavailable, never Gemini or a guess. A live-Gemini demo needs separate PO authorisation.
- **D12 (2026-10-03):** Option A, fixed inside CHG-006. The S6 walkthrough runs Mon 12, then Thu 15, then Fri 16, and ends at Prime Chem PAY on Thu 22 with ₹3,83,000 lowest. See AC9.

## Expected paths
- `app/web/`
- `app/main.py`
- `app/config.py`
- `app/ledger/writer.py`
- `app/domain/states.py`
- `app/db/read.py`
- `app/db/connection.py`
- `app/ledger/reconcile.py`
- `app/jobs/replan.py`
- `app/clock.py`
- `app/demo.py`
- `app/worker.py`
- `app/jobs/queue.py`
- `app/ai/fixture_backend.py`
- `Makefile`
- `fixtures/test_inbox/ai_replies.json`
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
- `tests/test_replan.py`
- `tests/test_ledger_writer.py`
- `tests/test_snapshot_builder.py`
- `tests/test_reconcile_owner_paid.py`
- `tests/test_reconcile_match.py`
- `tests/test_eml_folder.py`
- `tests/test_demo_mode.py`
- `fixtures/test_inbox/README.md`

## Open Questions
None. PO accepted every default on 2026-10-03 (see the plan's PO decisions).

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 5
- 2026-10-03: planned for batch 3 (lane sliced: five screens and about 20 routes can't be shown on one screen; cross-module). PO scope: login with argon2 and itsdangerous, CSRF on every POST, role dependency on every route, the TDD routes minus Gmail, stale-plan refusal, plain-text AI output, vendored HTMX and Pico, demo login, helper 403 matrix, web never imports ai.
- 2026-10-03: PO approved the batch 3 plan; status ready, batch 3.
