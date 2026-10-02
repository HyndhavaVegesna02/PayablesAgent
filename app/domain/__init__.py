"""Pure domain types (Pydantic models, state tables). No I/O, imports nothing
else from `app` (import-linter enforced, see pyproject.toml). Real types land
in CHG-002; this phase only needs the package to exist for the linter."""
