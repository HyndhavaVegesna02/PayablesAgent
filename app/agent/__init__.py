"""The exception agent (TDD Part 2, "Agent loop"; batch 6, CHG-008). It works
the cases plain code could not settle, one Gemini call per step with the case
file, through five tools. It finds evidence and proposes candidates; it never
changes ledger state (import-linter: it does not import app.ledger.writer, and
its only SQL writes are candidate, owner_question and its own agent_case row)."""
