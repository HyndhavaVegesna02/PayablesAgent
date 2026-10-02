# Batch 0 — Plan

Covers: CHG-001 (the only change in this batch). Lane: `planned`.

## Intent

Prove the scaffolding runs before any product behavior is built on it. A clean
checkout can set up its environment, create and migrate the database, seed the
worked-example business, start the web process, and pass CI — all with no AI
calls and no ledger-writing logic yet. Afterward: `make setup && make db &&
make seed && make run` works on a machine that has never seen this repo, and
`GET /api/health` returns 200.

## Program design

File-tree (everything new):

```
cashflow-agent/                          # repo root — Makefile etc. live at repo root per TDD
  Makefile
  pyproject.toml
  .env.example
  .gitignore
  config.yaml
  app/
    main.py                FastAPI app factory, GET /api/health
    config.py              Pydantic settings, loads config.yaml
    clock.py                Clock protocol, SystemClock, FakeClock
    domain/
      __init__.py           placeholder — real types land in CHG-002
    db/
      schema.sql             all 20 tables + account_balance view, verbatim from TDD Part 2
      migrations/
        0001_init.sql        applies schema.sql
      read.py                read-only connection (mode=ro)
    trace/
      tracer.py              JSONL writer: traces/<date>/<run_id>.jsonl
      view.py                `python -m app.trace.view <run_id>`
    jobs/
      queue.py                enqueue + claim via UPDATE … RETURNING
  fixtures/
    seed.py                   loads the Part 1 worked-example business
  .github/
    workflows/
      ci.yml                  make setup && make db && make test
  tests/
    test_schema.py
    test_clock.py
    test_jobs_queue.py
    test_health.py
  .importlinter                 (or [tool.importlinter] in pyproject.toml)
```

Types and signatures for the pieces with actual logic:

```python
# app/clock.py
class Clock(Protocol):
    def now(self) -> datetime: ...
    def today(self) -> date: ...

class SystemClock:
    def now(self) -> datetime: ...   # datetime.now(tz=ZoneInfo("Asia/Kolkata"))
    def today(self) -> date: ...

class FakeClock:
    def __init__(self, at: datetime) -> None: ...
    def advance(self, delta: timedelta) -> None: ...
    def now(self) -> datetime: ...
    def today(self) -> date: ...

# app/jobs/queue.py
def enqueue(conn, kind: str, payload: dict, idempotency_key: str | None, run_after: str) -> int: ...
def claim_one(conn, kinds: list[str] | None = None) -> JobRow | None: ...
    # UPDATE job SET status='running', locked_at=? WHERE id = (
    #   SELECT id FROM job WHERE status='queued' AND run_after <= ? ORDER BY id LIMIT 1
    # ) RETURNING *
def mark_done(conn, job_id: int) -> None: ...
def mark_failed(conn, job_id: int, error: str) -> None: ...   # backoff + dead after max_attempts

# app/trace/tracer.py
class Tracer:
    def __init__(self, run_id: str, trace_dir: Path) -> None: ...
    def step(self, **fields) -> None: ...   # one JSON line per call; fields per Part 1's trace table
```

No call-stack tree — this phase has no orchestration logic, just independent
pieces wired together at `main.py`/`Makefile` level.

## Contracts consumed

None. Phase 0 makes no call to Gemini, Gmail, or any interface outside this
repo. The contract trigger does not fire; `lane: planned` is chosen for scope
(touches many modules in one coherent session), not for this reason.

## Fixture sources

`fixtures/seed.py` loads amounts and dates directly from Part 1's worked
example (TDD section "Worked example"): business with safety amount
₹2,50,000, payment days Monday/Thursday, horizon 12–25 Oct 2026; the seven
ledger rows in that table as `bank_account`/`payable`/`receivable` rows. These
are real numbers from an authored, reconciling example, not invented fixtures.

## Steps

TDD-shaped: failing test → watch it fail for the right reason → minimal code →
pass → commit. Roughly in this order (parallelizable within a step where noted):

- [ ] S1: `pyproject.toml`, `Makefile` (`setup`, `db`, `seed`, `run`, `worker`
      as real targets; `test` wired to pytest+Hypothesis+import-linter;
      `evals`/`ablation` as stub targets that exit 1 with "not yet implemented"),
      `.env.example`, `.gitignore`, `config.yaml`. No test — this step is
      infrastructure; verified by S2 onward actually running.
- [ ] S2: `app/clock.py`. Test: `FakeClock` advances deterministically;
      `SystemClock.now()` is tz-aware (Asia/Kolkata).
- [ ] S3: `app/db/schema.sql` + `0001_init.sql`, transcribed verbatim from TDD
      Part 2. Test: `make db` on a scratch path creates all 20 tables + the
      `account_balance` view; `UPDATE`/`DELETE` on `event` raises.
- [ ] S4: `app/db/read.py` read-only connection helper. Test: a write attempted
      through it raises (SQLite `mode=ro`).
- [ ] S5: `app/jobs/queue.py`. Test: two concurrent `claim_one` calls on one
      queued row — exactly one succeeds (simulate with two connections/threads).
- [ ] S6: `app/trace/tracer.py` + `view.py`. Test: a sample `.step()` call
      writes one JSON line with the fields from Part 1's trace table; `view.py`
      prints it readably.
- [ ] S7: `app/config.py` — Pydantic settings loading `config.yaml` and `.env`.
      Test: a missing required env var fails fast with a clear error.
- [ ] S8: `app/main.py` — FastAPI factory, `GET /api/health` (DB reachable,
      queue depth, no worker heartbeat yet since the worker doesn't exist
      until later phases — report `worker: "not yet implemented"`). Test:
      `httpx` test client, 200 with the expected JSON shape.
- [ ] S9: `fixtures/seed.py`. Test: `make seed` against a scratch DB produces
      the worked-example business with the exact amounts in Part 1's table.
- [ ] S10: import-linter config (`domain` imports nothing from `app`;
      `planner` imports only `domain`; `ai` never imports `ledger`/`db`/`web`).
      Test: a deliberately-broken import added to a scratch probe file (outside
      the commit) proves the linter catches it, then the probe is discarded —
      record this as a note in the implementer's report rather than committing
      the probe.
- [ ] S11: `.github/workflows/ci.yml` running `make setup && make db &&
      make test` on push. Verified by a green run once pushed (CI gate run is
      part of batch close, not this step's local gate).
- [ ] S12: Update `CLAUDE.md`'s "Commands" section with the real Makefile
      targets (replacing the "once CHG-001 lands" placeholder).

## Review notes

Nothing here consumes an external contract and nothing here touches the ledger
writer or planner, so the review-checklist's contract-enumeration section does
not apply to this change. Standard cross-change checks don't apply either —
this batch has exactly one change.
