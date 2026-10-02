# PayablesAgent — SME Cash-Flow & Payables Agent

An agentic cash-flow planning system for a small Indian manufacturer. It reads
Gmail and owner uploads, keeps a deterministic ledger, plans 14 days ahead
against an owner-set safety amount, and re-plans as reality changes. It never
moves money — the owner approves the plan and pays through his own bank app.

Full product and build spec: `SME_Cash_Flow_Payables_Agent_TDD_v2.md` (Part 1 =
product spec, Part 2 = build spec — names, schema, routes, jobs are exact and
authoritative). Hackathon brief: `hackathon-2026-announcement_revised.md`.

## Architecture in one line

AI reads the messy world at the edges (Gmail, uploads); plain code owns every
number in the middle (ledger, planner, rule checks). The model never calculates
an authoritative value and has no tool that approves a payment or marks one paid.

## Stack

Python 3.12 (uv), FastAPI + Jinja/HTMX/Pico.css, SQLite (WAL), Gemini 3.8 Flash
(the only AI model — no Groq or Claude models in the product itself), pytest +
Hypothesis for tests, GitHub Actions for CI. Money is integer paise everywhere —
no float ever holds an amount.

## Commands

- `make setup` — creates the uv-managed virtualenv, installs pinned dependencies, and copies `.env.example` to `.env` if `.env` doesn't exist yet
- `make db` — applies `app/db/migrations/*.sql` (idempotent) and regenerates `app/db/schema.sql` from the live database
- `make seed` — loads the worked-example business from the TDD through the ledger writer; a second run is a no-op (it never deletes rows, because events are append-only)
- `make reseed` — deletes the database file at `DATABASE_PATH`, then migrates and seeds from scratch
- `make run` — starts the FastAPI web process on port 8000 (`GET /api/health`)
- `make test` — runs pytest (incl. Hypothesis properties) and import-linter
- `make worker` — runs the job worker and the scheduler (`python -m app.worker`); it writes a heartbeat that `/api/health` reports
- `make smoke-gemini` — live and billed: at most 3 Gemini calls (sort and extract on two test-inbox fixtures) to check the prompts on Gemini itself; never part of `make test`, and run only when the PO authorises it
- `make evals`, `make ablation` — intentional stub failures until Phase 9 implements them — they exist in the Makefile so nothing is silently green

## Invariants that hold across every change

- Money is integer paise everywhere; no float ever holds an amount.
- Every payable/receivable/transaction state change goes through
  `app/ledger/writer.py::transition()` — nothing else updates a state column.
- `app/planner/` is a pure function: no I/O, no clock, no network.
- All code reads time through `app/clock.py`'s `Clock` interface.
- `app/ai/` never imports `ledger`, `db` or `web` (import-linter enforced).
- The AI has no tool that approves a payment, marks a bill paid, or sends
  anything outside the app.

## Development process

This project runs on **YourTeam** (`.claude/skills/yourteam/SKILL.md`) — a
risk-routed development loop. All code changes go through `.yourteam/`: a
backlog entry, a lane-appropriate plan, mechanical gates, and a batched review.
Start a session by invoking the `yourteam` skill; it reads `.yourteam/batch.yaml`
and reports the current state.
