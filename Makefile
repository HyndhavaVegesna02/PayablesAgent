.PHONY: setup db seed reseed run worker demo-time test smoke-gemini evals ablation

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

evals:
	@echo "make evals: not yet implemented (lands with Phase 9)" >&2
	@exit 1

ablation:
	@echo "make ablation: not yet implemented (lands with Phase 9)" >&2
	@exit 1
