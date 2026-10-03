.PHONY: setup db seed reseed run worker demo-time test smoke-gemini evals ablation workflow

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
evals:
	uv run python -m evals.runner $(ARGS)

# make ablation ARGS="--ai fixtures"   (live: --ai live --yes-spend; see README)
ablation:
	uv run python -m evals.ablation $(ARGS)

# The scripted fortnights through the real web app, worker and demo clock (CHG-027).
# make workflow               both runs, offline (fixture AI)
# make workflow RUN=B N=3     one run, three repeats
# make workflow AI=live ARGS=--yes-spend   live Gemini, behind the budget guard; only when authorised
workflow:
	uv run python -m evals.workflow --ai $(or $(AI),fixtures) $(if $(RUN),--run $(RUN)) $(if $(N),--runs $(N)) $(ARGS)
