# Batch 1 — Review

Changes: CHG-011 (direct), CHG-002 ledger core (planned), CHG-003 planner (planned). CHG-012 was dropped by the PO at plan approval.

The review was split by subsystem, as the PO suggested for a large diff: about 1,650 production lines and 2,200 test lines. Each reviewer ran as a general-purpose agent bound by `.claude/agents/yt-reviewer.md`. Ledger covered CHG-002 and CHG-011. Planner covered CHG-003. Both read the ledger↔planner seam.

## Round 1 — both FIX_REQUIRED

**Ledger: 3 critical, 3 major, plus 2 cross-change majors**
- `test_seed.py::test_fresh_*` could not fail: a no-op `--fresh` passed it.
- `test_second_owner_action_*` went through SPLIT, which is refused before any versioning check, so it never tested versioning.
- Dead code: `BANK_TXN_STATES`, `RECEIVABLE_STATES` and the `Event` model.
- `payable_amount_paise` was unchecked, so a float could be stored as an amount.
- A MISSING tax amount created an obligation with no statutory payable. That was never approved.
- SPLIT atomicity had no driving test.
- Cross-change: the writer accepted discounts that `build_snapshot` would then refuse for the whole business.
- Cross-change: the float hole could reach the planner.

**Planner: 2 critical, 2 major**
- `build_snapshot` ran 4 SELECTs with no read transaction. A write landing between them overstated cash by the bill amount.
- Invariant I1 was a tautology. I2 couldn't catch double counting. Mutation: 19 of 24 mutants survived the property file.
- WAIT was decided on the due date rather than on the target, as plan step 4(d) requires, so a safe discount on a bill due after the horizon was lost.
- Breach day and gap were tested only where they coincide with the target day (mutants M24/M25 survived).

## Fix round 1 — 140b292 (ledger), de8725f (planner)

Every finding was fixed. Each repaired or new test was mutation-checked: a mutant was inserted and the test was confirmed to fail.

The fixes:
- The fresh test plants a marker row.
- The locking test makes a real stale PAID move.
- Dead code is removed.
- `payable_amount_paise` must be positive int paise.
- MISSING tax amounts are refused (open PO question).
- `PayableNew` refuses discount ≥ amount and unpaired discount fields.
- A split-atomicity test was added.
- `build_snapshot` reads inside one read transaction.
- I1 is rebuilt from PAY bills only, and I2 checks completeness and no repeats.
- WAIT is decided on the target.
- A breach test at non-aligned days was added.

Re-review results:
- Ledger: **APPROVE**.
- Planner: FIX_REQUIRED, one new major. `delay_flexible` kept the early-payment discount in its what-if, so the option named a delay its own re-run never applied.

## Fix round 2 — 88da9cf

The `delay_flexible` what-if now drops the discount, with a test that is mutation-checked. Small ledger tidy-ups went into the same commit: `PAYABLE_STATES` is now derived from the `PayableStatus` Literal, and the MISSING-tax question is listed under CHG-002's Open Questions.

Planner re-review: **APPROVE**. Of the reviewer's 35 mutants, two survive the full suite:
- M11, which is behaviour-equivalent.
- M34, the split rest part keeping grace days. It has no driving test, because the what-if snapshot isn't exposed. Accepted as a note.

## Final verdicts

| Change | Reviewer | Criteria |
|---|---|---|
| CHG-011 | APPROVE | AC1–AC2 MET |
| CHG-002 | APPROVE | AC1–AC12 MET |
| CHG-003 | APPROVE | AC1–AC9 MET (AC8 wording, see below) |

**Dependency:** CHG-003 depends on CHG-002. The snapshot builder reads the writer's schema and seed, and the planner uses `format_inr`. They cannot be accepted separately. CHG-011 is independent.

## For the PO at verdict

1. **MISSING tax amounts (CHG-002).** `create_tax_obligation` currently refuses `amount_status = MISSING`. The TDD has every obligation create a statutory payable, and a payable needs an amount. How should a MISSING amount be tracked?
2. **AC8 wording (CHG-003).** WAIT follows approved plan step 4(d), deciding on the target. So a bill due after the horizon still gets a PAY line when its latest payment day before the due date, or a safe discount day, is inside the horizon. Example: Thursday-only payment days and a bill due Tue 27 → PAY Thu 22. That narrows AC8's literal "bills due after the horizon get WAIT". The alternative is a literal due-date rule.

## Notes carried, not blocking

- Split rest part grace days are untested (M34).
- The `PYTHONHASHSEED` check guards str hashing only.
- `bank_account.status` is not read.
- Seed reads `DATABASE_PATH` from the environment, while the app reads `Settings` (pre-existing).
- The `AlreadySeeded` check has a TOCTOU gap.
- The tax link path doesn't check the linked payable's status.
- What-if split ids (−payable_id) must never be persisted (noted in CHG-013).
