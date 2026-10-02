"""The only code that calls Gemini. Never imports app.ledger, app.db or
app.web (import-linter enforced, see pyproject.toml). Real client lands in
CHG-004; this phase only needs the package to exist."""
