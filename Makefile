.PHONY: setup db seed reseed run worker test evals ablation

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
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

worker:
	uv run python -m app.worker

test:
	uv run pytest -q
	uv run lint-imports

evals:
	@echo "make evals: not yet implemented (lands with Phase 9)" >&2
	@exit 1

ablation:
	@echo "make ablation: not yet implemented (lands with Phase 9)" >&2
	@exit 1
