# app/validate: the rule checks

Plain code that decides whether an extracted record may reach the ledger (TDD Part 1, "Rule checks"). Every candidate runs through these checks. The model never decides whether a record passes.

## The rule: pure functions only

- A check takes plain values (int paise, dates, strings) and returns one check string: `passed`, `failed: <why>`, `not_applicable` or `skipped: <why>`. These are defined in `__init__.py`.
- No I/O. No database, no files, no network, no clock: nothing in here reads the time, and the business's time zone comes from `app.domain.time`.
- When a check needs to know whether something already exists (a duplicate), the caller passes a lookup function in. The lookups live in `app/db/read.py`.
- From `app`, it imports only `app.domain` and itself.

Two things enforce this:
- the import-linter contract "validate is pure: imports only domain" (pyproject.toml);
- `tests/test_validate_boundary.py`, which fails if any module here imports `sqlite3`, `os`, `pathlib`, `socket`, `httpx`, `io`, `subprocess`, `shutil` or `logging`.

## Modules

| Module | Checks |
|---|---|
| `alert.py` | bank alerts and failure notices: schema, amount, account, dates, duplicates, confidence |
| `dates.py` | mail dates (an alert can't postdate its email) |
| `duplicates.py` | dedup keys built by code from what was read |
| `gstin.py` | GSTIN format and mod-36 check character |
| `arithmetic.py` | invoice arithmetic (exact, plus an explicit round-off line of at most ₹1.00: D19) and statement arithmetic |
| `invoice.py` | an invoice read from an email, photo or PDF: amounts, GSTIN, arithmetic, dates, duplicates (through a lookup), confidence; bill or sales invoice by name |
| `statement.py` | a bank statement: account, amounts, balances, arithmetic, dates in the period, duplicates, confidence |
| `voice.py` | a bill told in a voice note: the spoken amount, read by code, must equal in paise the one money-shaped amount code reads in full from the transcript (D29) |
| `bank.py` | vendor bank details: last four digits, IFSC, what counts as a change, the owner's question |
| `summary.py` | a plan's "what changed" text: every amount and date must be one the plan diff holds; no other digit, no markup, at most 600 characters |
