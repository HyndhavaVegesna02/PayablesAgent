.PHONY: setup db seed reseed run worker demo-time test smoke-gemini evals ablation workflow check-evidence
.PHONY: run-shrimp worker-shrimp reseed-shrimp demo-time-shrimp rehearse-shrimp

setup:
	uv sync --all-groups
	@test -f .env || cp .env.example .env

db:
	uv run python -m app.db.migrate

seed:
	uv run python -m fixtures.seed

reseed:
	uv run python -m fixtures.seed --fresh

run:
	uv run uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000

worker:
	uv run python -m app.worker

# Demo mode only (DEMO_NOW set): move the shared demo clock forward, e.g.
# make demo-time T=2026-10-15T09:00:00+05:30
demo-time:
	uv run python -m app.demo $(T)

test:
	uv run pytest -q
	uv run lint-imports

# Live and billed: at most 3 Gemini calls. Never part of `make test`; run only when authorised.
smoke-gemini:
	uv run python -m app.ai.smoke --yes-call-gemini

# make evals ARGS="--ai fixtures --runs 5"   (live: --ai live --yes-spend; see README)
# The report goes to docs/evals/raw-runs/<date>-<mode>-<label>/.
evals:
	uv run python -m evals.runner $(ARGS)

# make ablation ARGS="--ai fixtures"   (live: --ai live --yes-spend; see README)
# The report goes to docs/evals/raw-runs/<date>-<mode>-<label>/.
ablation:
	uv run python -m evals.ablation $(ARGS)

# The scripted fortnights through the real web app, worker and demo clock (CHG-027).
# make workflow               both runs, offline (fixture AI)
# make workflow RUN=B N=3     one run, three repeats
# make workflow AI=live ARGS=--yes-spend   live Gemini, behind the budget guard; only when authorised
# The reports go to docs/evals/4-end-to-end-workflows/.
workflow:
	uv run python -m evals.workflow --ai $(or $(AI),fixtures) $(if $(RUN),--run $(RUN)) $(if $(N),--runs $(N)) $(ARGS)

# Every committed fixture-mode report in docs/evals/ (its numbered folders and raw-runs/) still says what the
# code emits, and every combined page re-derives from its raw runs (CHG-032, CHG-055).
# About a minute; not part of make test; required at batch close (.yourteam/definition-of-done.md).
check-evidence:
	uv run python scripts/check_evidence.py

# The shrimp-farm demo profile (CHG-058; dev only). .env.shrimp is applied as process environment
# (scripts/with_env.py); .env is never read or changed by these targets. FALLBACK=1 adds
# .env.shrimp-fixtures: the worker answers from canned replies, never Gemini.
#   make reseed-shrimp; make run-shrimp; make worker-shrimp; make demo-time-shrimp T=2026-10-20T10:00:00+05:30
SHRIMP_ENV = .env.shrimp $(if $(FALLBACK),.env.shrimp-fixtures)

run-shrimp:
	uv run python scripts/with_env.py $(SHRIMP_ENV) -- python -m uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000

worker-shrimp:
	uv run python scripts/with_env.py $(SHRIMP_ENV) -- python -m app.worker

reseed-shrimp:
	uv run python scripts/with_env.py $(SHRIMP_ENV) DATABASE_PATH=./data/shrimp.db -- python -m fixtures.shrimp_seed --fresh

demo-time-shrimp:
	uv run python scripts/with_env.py $(SHRIMP_ENV) -- python -m app.demo $(T)

# The shrimp fortnight's moves 1-6 through the real routes, worker and demo clock (CHG-058).
# make rehearse-shrimp                      offline (canned replies), free
# make rehearse-shrimp ARGS="--ai live --yes-spend --max-usd 1.00"   live Gemini under the budget guard; only when authorised
# Reports and traces go to rehearsals/ (git-ignored).
rehearse-shrimp:
	uv run python scripts/rehearse_shrimp.py $(or $(ARGS),--ai fixtures)
