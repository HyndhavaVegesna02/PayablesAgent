---
id: CHG-001
title: Repo skeleton — layout, config, schema, Clock, tracer, job table, CI
type: feature
lane: planned
---

## Context
TDD: `SME_Cash_Flow_Payables_Agent_TDD_v2.md`, Part 2, "MVP build sequence", Phase 0.
This is the foundation every later phase builds on: nothing else can be built,
tested or gated until a clean checkout can set up, migrate, seed and run.

## Description
Build the repo skeleton exactly as specified in Part 2:

- Repository layout under `cashflow-agent/` (Part 2, "Repository layout")
- `Makefile` targets: `setup`, `db`, `seed`, `run`, `worker`, `test`, `evals`, `ablation`
  (`evals`/`ablation` may be stub targets that fail loudly with "not yet implemented"
  until their phases land — they must exist and must not be silently green)
- `pyproject.toml` pinned via `uv`, Python 3.12
- `.env.example` listing every variable from Part 2, "Dependencies and environment"
- `app/config.py` — Pydantic settings, loads `config.yaml` (Part 2, "Tracing, configuration and security")
- `app/clock.py` — `Clock` protocol, `SystemClock`, `FakeClock`
- `app/db/schema.sql` — all 20 tables and the `account_balance` view, verbatim from
  Part 2's "Database schema" section, including the `event` append-only triggers
- `app/db/migrations/0001_init.sql` applying that schema
- `app/db/read.py` — read-only connection helper (`mode=ro`)
- `app/trace/tracer.py` — writes one JSON Lines file per run to `traces/<date>/<run_id>.jsonl`
  with the fields listed in Part 1, "Traces and audit trail"
- `app/jobs/queue.py` — SQLite-backed job table: enqueue, and claim via `UPDATE … RETURNING`
- `fixtures/seed.py` — loads the worked-example business from Part 1 (safety amount
  ₹2,50,000, payment days Monday/Thursday, the accounts/parties/payables/receivables
  from the worked example)
- `.github/workflows/ci.yml` — runs `make setup`, `make db`, `make test` on every push
- `app/main.py` — FastAPI app factory with `GET /api/health`
- import-linter config enforcing the dependency rules in Part 2, "Repository layout"
  ("Dependency rules" subsection)

No AI calls, no web routes beyond `/api/health`, no ledger writer logic — those are
later phases. This phase proves the scaffolding runs, not that the product works.

## Acceptance Criteria
- [ ] AC1: `make setup` creates a virtualenv and installs pinned dependencies on a clean checkout, exit 0
- [ ] AC2: `make db` applies `db/migrations/0001_init.sql` and creates every table and the `account_balance` view from Part 2's schema, exit 0
- [ ] AC3: The `event` table rejects `UPDATE` and `DELETE` (the append-only triggers fire), verified by a test that expects the `ABORT`
- [ ] AC4: `make seed` loads the worked-example business, accounts, parties, payables and receivables from Part 1's worked example, exit 0
- [ ] AC5: `make run` starts the FastAPI process on port 8000; `GET /api/health` returns 200 with database and queue-depth status
- [ ] AC6: `make test` runs pytest, Hypothesis and import-linter and is green on a clean checkout
- [ ] AC7: CI runs `make setup`, `make db`, `make test` on every push and is green
- [ ] AC8: No code outside `app/clock.py` calls `datetime.now()`, `date.today()` or equivalent directly — a `FakeClock` test proves at least one consumer (e.g. the job queue's `run_after`) is time-injectable
- [ ] AC9: `app/trace/tracer.py` writes a JSON Lines file with the fields from Part 1 ("Traces and audit trail") for a sample step, and `python -m app.trace.view <run_id>` prints it as readable steps
- [ ] AC10: `app/jobs/queue.py` can enqueue a job row and claim it exactly once under a simulated concurrent claim (two claims racing for one row never both succeed)
- [ ] AC11: import-linter fails the build if `domain` imports anything else from `app`, if `planner` imports anything but `domain`, or if `ai` imports `ledger`, `db` or `web` — proven by a deliberately-broken probe reverted before commit, or an equivalent unit test of the linter config

## Expected paths
- `Makefile`, `pyproject.toml`, `.env.example`, `.gitignore`
- `app/main.py`, `app/config.py`, `app/clock.py`
- `app/db/schema.sql`, `app/db/migrations/0001_init.sql`, `app/db/read.py`
- `app/trace/tracer.py`, `app/trace/view.py`
- `app/jobs/queue.py`
- `app/domain/` (empty-module placeholders only — real types land in CHG-002)
- `fixtures/seed.py`
- `.github/workflows/ci.yml`
- `tests/test_schema.py`, `tests/test_clock.py`, `tests/test_jobs_queue.py`, `tests/test_health.py`
- `config.yaml`
- `CLAUDE.md` (build/test/run commands section)

## Open Questions
<!-- none -->

## History
- 2026-10-02: drafted from TDD v2.0 Part 2, Phase 0; pulled into batch 0
