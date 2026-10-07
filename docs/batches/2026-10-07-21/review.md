# Batch 21 review: the shrimp-farm demo profile (CHG-057, CHG-058)

One yt-reviewer read the whole batch, range 5f79c32..8e95979, then each fix round.

## Round 1 (8e95979): FIX_REQUIRED

Every acceptance criterion met; none of the PO's hard constraints broken (no protected path changed; no secret in
the profile files; environment over .env; reseed-shrimp writes ./data/shrimp.db only; every state change through
transition(); amount_paise never edited; model-written text escaped). Two majors, both in CHG-057:

- **M1.** The explain_credit card said "counted in the plan" for any COMMITTED invoice. The planner counts one only
  from today to the horizon's end (app/db/read.py), so a COMMITTED invoice past its date (the late-payment case
  that raises ambiguous_match) was shown as counted. Came in with 46ea2a2, after CHG-057's gate.
- **M2.** The owner-alias rule was written twice, in explain_debit and explain_credit.

Minors: a literal backslash-n in the Makefile's .PHONY line; _settle_case's docstring named only debits; the
settled-meanwhile paths of the two mirror functions had diverged; repo.credit and repo.debit near-identical; the
shrimp seed's clock reset follows DATA_DIR, so a hand run with only DATABASE_PATH set would reset the worked
example's demo clock; two rehearsals in one second collide; a dated status line in docs/demo-shrimp.md. Noted and
deferred: case_finding's " | " split and the 20-line cut; a RESOLVED summary shown twice on the page; ShrimpRun
copies Run.__init__ (evals/ can't change); the agent-permissions note's unrelated no-due-date rewording. A process
note for the PO: starting `make run-shrimp` to check it had Settings read .env (nothing printed or written).

## Fix round 1 (1ecb36d)

M1: each offered invoice is marked counted from the planner's own snapshot for today
(`build_snapshot(...).inflows`, as present.money_in does), with a test for Kaveri on Sat 17 Oct. M2: one
_alias_payer, one _settle_txn_questions(kind), one repo.bank_txn(direction). The cheap minors fixed; the seed
also refuses a DATA_DIR other than ./data/shrimp-files, with a test.

## Round 2 (1ecb36d): FIX_REQUIRED

M1, M2 and the minors verified fixed. One new blocking finding: the new DATA_DIR test aimed the seed at the real
./data/shrimp.db and relied on the guard under test to stop the reseed, so a broken guard (or a replay against an
older tree in the main checkout) would delete the Demo Day database.

## Fix round 2 (6379c37)

The test points the module's SHRIMP_DB and SHRIMP_FILES at tmp and asserts no database was made; the rehearsal
folder's suffix loop has no fall-through.

## Round 3 (6379c37): APPROVE

The test now aims only at tmp (the reviewer simulated a broken guard: only tmp was touched, and the real
./data/shrimp.db kept its modified time); the folder loop always ends with a folder. Every acceptance criterion
of CHG-057 and CHG-058 stays met; no open critical or major finding. The deferred minors and the .env process
note go to the PO with the report.

## Verdict

PO (payablesagent-ac), 2026-10-07: CHG-057 and CHG-058 ACCEPTED. At batch close Windows Application Control
blocked `make` (exit 4551, then "make: Permission denied"), so the close gate at 3396c8e recorded make test and
make check-evidence as POLICY BLOCK; those red entries stay. The PO verified both changes on its own direct-command
evidence at 16a5467, in C:\Hyn\PayablesAgent-uicheck, with no Gemini: pytest 1962 passed; lint-imports 9 contracts
kept; check_evidence 8 of 8 reproduce; the offline driver passed all 7 moves (agent-finding-shown on moves 2 and 5;
the advance MATCHED and CONFIRMED; HARVEST-BAL CONFIRMED with "short by ₹95,000"; the floor held, lowest ₹4,35,200);
protected paths a zero diff against 5f79c32. It also read migration 0006, .env.shrimp and the explain_credit
template. Pushes authorised: dev to origin main (fast-forward); public untouched. No live rehearsal until the
user's billing headroom and the real voice note and photo are in. CHG-059 also takes the driver's `shortfall` check,
which reads backwards in the report.
