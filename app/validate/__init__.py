"""Rule checks: plain code, run on every candidate (TDD Part 1, "Rule
checks"). Each check's result is one string, recorded in candidate.checks_json:
- "passed"
- "failed: <why>"  (the why goes back to the model on a retry)
- "not_applicable" (the check does not apply to this kind of document)
- "skipped: <why>" (it could not run, e.g. the reply did not match the schema)
"""

from __future__ import annotations

PASSED = "passed"
NOT_APPLICABLE = "not_applicable"

# Every Part 1 rule check, in the order they are recorded.
CHECK_NAMES = (
    "schema", "amount", "balance", "account", "dates", "duplicates", "confidence",
    "gstin", "invoice_arithmetic", "statement_arithmetic",
)
# Checks for bills, invoices and statements; they land with CHG-007 (batch 2 plan, Q3).
NOT_FOR_MAIL_ALERTS = ("gstin", "invoice_arithmetic", "statement_arithmetic")


def failed(why: str) -> str:
    return f"failed: {why}"


def skipped(why: str) -> str:
    return f"skipped: {why}"


def failures(checks: dict[str, str]) -> dict[str, str]:
    return {k: v.removeprefix("failed: ") for k, v in checks.items() if v.startswith("failed: ")}
