# Batch 1 — Plan

Covers: CHG-011, CHG-012 (direct), CHG-002 ledger core (planned), CHG-003 planner (planned).
Branch: `batch-1` from `main`. Order: 011 → 012 → 002 → 003 (003 consumes 002's writer, seed and money formatter).
Work inline: the context is warm, and there's one implementer with no concurrency, because 002 and 003 share `fixtures/seed.py` and `app/db/read.py`.

**Router.**
- CHG-002 → `planned`. Trigger: *migrates or deletes data*. D3 replaces the seed's DELETE-and-reinsert with recreate-the-file, which changes what happens to an existing dev database.
- CHG-003 → `planned`, capped there. Trigger: *consumes a contract it didn't write*. The planner reads the snapshot that CHG-002's schema and writer produce (units, empty/absent rules), so the contract grid below is mandatory.
- CHG-011, CHG-012 → `direct`. No trigger fires.

The PO's standing policies (2026-10-02) apply throughout:
- No live Gemini calls anywhere; this batch makes no AI calls at all.
- Never read, print or commit `.env`.
- No Gmail/OAuth code.
- Local `make test` through `yt_gate.py` is the gate of record; CI and CHG-001's AC7 are waived.

---

## Intent

After this batch, the deterministic middle of the system exists and can be shown to be honest.

**The writer.** Every change to a bill, receivable or bank transaction goes through one function. It refuses any `agent:` actor and any illegal or stale move, and it writes its audit event in the same SQLite transaction.

**The planner.** It is a pure function, and it reproduces Part 1's worked example **from the seeded database**, byte-identical across runs:
- all 14 daily balances;
- ₹1,83,000 on Thu 22 Oct, with Prime Chem on ESCALATE;
- the three options: Nandi pays by Fri 16 Oct → ₹3,83,000; split ₹53,000 now / ₹67,000 after 25 Oct → ₹2,50,000; authorise the breach → ₹67,000 below.

**How to see it worked:**
- `make reseed && make test` is green.
- `tests/test_planner_golden.py` passes.
- `SELECT event_type, actor FROM event` on a seeded DB shows the full trail: each record's creation and each bill's confirmation.

---

## CHG-011 (direct) — one-line plan
`/api/health` calls `app.db.read.read_only_connection()` instead of hand-building the `mode=ro` URI. A new test spies on `app.main.read_only_connection` and asserts it is called; it fails at the start commit because that name doesn't exist in `app.main` yet. Existing `tests/test_health.py` is unchanged.

## CHG-012 (direct) — one-line plan
Factor `(clock or SystemClock()).now().isoformat()` into `_now_iso(clock)` in `app/jobs/queue.py`. No behaviour change and no new test, so prepatch replays nothing, which is expected for a pure refactor. The entry's own text says "not worth it for two call sites"; I'm doing it because the PO pulled it in. Say "drop 012" to skip.

---

## CHG-002 — Ledger core

### Program design

```
 app/
+  domain/money.py        # NEW — format_inr(paise) lakh formatter; int-only
+  domain/states.py       # NEW — transition tables (payable from Part 2; bank_txn, receivable per D2), actor parsing
+  domain/models.py       # NEW — Pydantic models for ledger records (StrictInt paise, Literal enums)
+  ledger/__init__.py     # NEW
+  ledger/writer.py       # NEW — the only writer of payable/receivable/bank_txn/tax_obligation/event
~ fixtures/seed.py        # MODIFIED — ledger rows through the writer (D3); refuses a non-empty DB
~ Makefile                # MODIFIED — `make reseed` (= python -m fixtures.seed --fresh)
~ pyproject.toml          # MODIFIED — D7 import-linter contract
~ CLAUDE.md               # MODIFIED — Commands: make reseed
+ tests/test_money.py  test_states.py  test_models.py  test_ledger_writer.py
+ tests/test_ledger_writer_stateful.py  test_ledger_write_guard.py
~ tests/test_seed.py
```

**Actors (`states.py`).** `parse_actor(actor) -> Role` follows these rules:
- Exactly four forms are accepted: `owner:<positive int>`, `planner`, `reconciler` and `pipeline`. The role is matched on the part before `:`.
- Any actor starting with `agent:` raises `AgentActorRefused`. This applies to every entity, every create and every transition, and the check runs **before** the table lookup, so editing the table can't bypass it.
- Anything else raises `InvalidActor`, for example `Owner:1`, `owner:`, `owner:abc` or `planner:1`.
- For `owner:<id>`, the writer also checks that `app_user.id` exists, has `role='owner'` and belongs to the entity's business. Otherwise it raises `ActorNotAllowed`, so a helper's id can never act as owner.

**Writer API (`ledger/writer.py`).** The TDD name and positional order are kept exactly; infrastructure arguments are keyword-only.

```python
@dataclass(frozen=True)
class EntityRef:
    kind: Literal["payable", "receivable", "bank_txn"]
    id: int

def transition(entity: EntityRef, to_state: str, actor: str, reason: str, source_ref: str | None, *,
               conn: sqlite3.Connection,
               expected_version: int | None = None,        # required when actor is owner:*
               fields: Mapping[str, object] | None = None, # only the per-move allow-list in states.TRANSITION_FIELDS
               trace_run_id: str | None = None,
               clock: Clock | None = None) -> Payable | Receivable | BankTxn

def create_payable(new: PayableNew, *, actor, reason, source_ref, conn, clock=None, trace_run_id=None) -> Payable   # status DRAFT
def create_receivable(new: ReceivableNew, *, ...) -> Receivable    # confidence COMMITTED | EXPECTED | UNKNOWN
def create_bank_txn(new: BankTxnNew, *, ...) -> BankTxn            # UNMATCHED (pipeline) or ADJUSTMENT (owner)
def create_tax_obligation(new: TaxObligationNew, *, payable_id: int | None = None, ...) -> TaxObligation
    # payable_id None → also creates its statutory payable (DRAFT, priority statutory, same amount + due date) and links it
def split_payable(entity: EntityRef, first_paise: int, second_due_date: date, actor, reason, source_ref, *,
                  conn, expected_version, clock=None, trace_run_id=None) -> tuple[Payable, Payable]
@contextmanager
def atomic(conn) -> Iterator[None]   # public so the reconciler can later group txn MATCHED + bill PAID
```

**What `transition` sets besides the state column.** Anything else is refused with `FieldNotAllowed`.
- `payable → PLANNED`: `planned_date` is required.
- `PLANNED → CONFIRMED` (a re-plan to WAIT): the writer clears `planned_date` to NULL.
- `→ PAYMENT_EXPECTED`: the writer sets `approved_by` to the owner actor's id and `approved_at` from the Clock.
- `payable → PAID` and `receivable → CONFIRMED`: `matched_txn_id` is optional.
- `bank_txn → MATCHED`: `party_id` is optional.

**The version bump and the event row share one transaction:**

```
transition(...)
  parse_actor / agent refusal                       # before any SQL
  with atomic(conn):                                # BEGIN IMMEDIATE, or SAVEPOINT if caller already in a transaction
    before = SELECT * FROM <table> WHERE id = ?     # NotFound if missing
    check (before.state, to_state) in TABLE[kind] and role in allowed  → IllegalTransition / ActorNotAllowed
    owner actor: expected_version required (VersionRequired) and == before.version (StaleVersion)
    UPDATE <table> SET <state>=?, version=version+1, <allowed fields>
      WHERE id=? AND <state>=? [AND version=?]      # compare-and-set; rowcount 0 → StaleVersion
    after = SELECT * ...
    _insert_event(entity, event_type, actor, before_json, after_json, reason, source_ref, trace_run_id, occurred_at=clock.now())
  # exception anywhere inside → ROLLBACK (or ROLLBACK TO savepoint) → version, state and event all unchanged
```

- `bank_txn` has no `version` column in the schema. Its moves compare-and-set on `status` only, and `expected_version` is ignored for it.
- **Event types.** Moves write `<ENTITY>_<TO_STATE>`, for example `PAYABLE_PLANNED` or `BANK_TXN_MATCHED`. Creates write `<ENTITY>_CREATED`, and splits write `PAYABLE_SPLIT`. I've treated Part 1's example `PAYMENT_PLANNED` as illustrative; say if you want that exact spelling.
- `before_json` and `after_json` hold the full row as JSON with `sort_keys=True`. Money stays int.
- **Rollback proof.**
  - One test monkeypatches `_insert_event` to raise after the UPDATE has run, then asserts that status, version and event count are all unchanged.
  - A second test runs two transitions in one `atomic()` block, with the second refused, and asserts the first was rolled back.

**Optimistic locking.**
- Every `owner:*` action must pass `expected_version`. A stale version raises `StaleVersion` and nothing is written.
- System actors (planner, reconciler, pipeline) may omit it. They are still protected by the status compare-and-set inside `BEGIN IMMEDIATE`.

**SPLIT.** Only the owner can split, from `CONFIRMED` or `PLANNED`, and `expected_version` is required. The inputs must satisfy `0 < first_paise < amount`, and `second_due_date` must be on or after the parent's due date.

One `atomic()` block does all of the following:
- The parent moves to `SPLIT` and its version goes up by one.
- Two children are inserted, each with `parent_payable_id = parent.id`. Both copy `party_id`, `invoice_number`, `invoice_date`, `priority`, `grace_days` and `source_document_id` from the parent.
- Child 1 gets `first_paise` and the parent's due date. Child 2 gets the rest and `second_due_date`.
- Both children have NULL discount fields and start in `CONFIRMED` (Q7).
- Three events are written: `PAYABLE_SPLIT` and two `PAYABLE_CREATED`, all with `source_ref='payable:<parent id>'`.

**Money.**
- `format_inr(paise: int) -> str` uses Indian grouping:
  - `28_200_000 → "₹2,82,000"`
  - `18_300_000 → "₹1,83,000"`
  - `1_000_000_000 → "₹1,00,00,000"`
  - `0 → "₹0"`
- Paise are shown only when they are non-zero: `5_050 → "₹50.50"`.
- Negatives get a leading minus: `-6_700_000 → "-₹67,000"`.
- A `bool` or `float` input raises `TypeError`.
- A Hypothesis round-trip property checks that stripping `₹` and `,` and parsing the result gives back the input.
- Every Pydantic money field is `StrictInt`, so `amount_paise=1800.0` is rejected when the model is validated.

### D2 — transition tables (every row cites the TDD; a row I couldn't cite is a question, not a guess; `agent:*` is refused for all of them)

**payable** — copied verbatim from Part 2, "Ledger writer". These 12 rows make up `PAYABLE_TRANSITIONS`, and a test asserts the table matches them exactly:

| From | To | Actor |
|---|---|---|
| DRAFT | CONFIRMED | owner |
| CONFIRMED | PLANNED | planner |
| PLANNED | CONFIRMED | planner |
| REOPENED | PLANNED | planner |
| PLANNED | PAYMENT_EXPECTED | owner |
| PAYMENT_EXPECTED | PAID | reconciler, owner |
| PAYMENT_EXPECTED | REVIEW | reconciler |
| PAYMENT_EXPECTED | REOPENED | reconciler |
| REVIEW | PAID | owner |
| REVIEW | REOPENED | owner |
| PAID | REOPENED | reconciler |
| CONFIRMED, PLANNED | SPLIT | owner (via `split_payable` only) |

A payable is created only in DRAFT, by `pipeline` or `owner`. The stateDiagram's `[*] --> DRAFT` covers the DRAFT start, but the creation actors aren't named in the TDD (Q7).

**bank_txn.status**

| From | To | Actor | Cite |
|---|---|---|---|
| (create) | UNMATCHED | pipeline | Part 2 "Reconciliation and drift › A new debit" step 5 ("the debit stays UNMATCHED", so it starts there); "Jobs › The pipeline" step 6 ("Bank alert or statement row: written to the ledger by the pipeline") |
| (create) | ADJUSTMENT | owner | "Drift check" step 6 ("writes an ADJUSTMENT transaction for the difference, with the owner as actor"); route `POST /accounts/{id}/confirm-balance` |
| UNMATCHED | MATCHED | reconciler | "A new debit" step 3 ("the debit is MATCHED and the bill becomes PAID"); "A new credit follows the same steps" |
| MATCHED | REVERSED | reconciler | "Failures and reversals" ("any original debit is marked REVERSED") |

Three moves aren't in the TDD. They are **refused** until Q5 is answered:
- UNMATCHED→EXPLAINED (who may make it is open);
- UNMATCHED→MATCHED by the owner, when they resolve a REVIEW bill as "paid";
- UNMATCHED→REVERSED.

**receivable.confidence.** Receivables have no status column, so `confidence` is their state.

| From | To | Actor | Cite |
|---|---|---|---|
| (create) | COMMITTED, EXPECTED, UNKNOWN | owner | "Jobs › The pipeline" step 6 ("sales invoice … shown to the owner to confirm (`confirm_record`), then written") |
| COMMITTED, EXPECTED, UNKNOWN | CONFIRMED | reconciler | "A new credit" ("A match marks the receivable CONFIRMED"); Part 1 "Worked example › What happens next" (Nandi, EXPECTED, "matched and marked CONFIRMED") |

Three moves aren't in the TDD. They are refused until Q6 is answered:
- the owner re-rating among COMMITTED/EXPECTED/UNKNOWN (for example, the customer gives a written date);
- creation by `pipeline`;
- any move out of CONFIRMED.

### D3 — seed with an audit trail

**Resolving the conflict with append-only events.** `seed(conn)` never deletes anything; if any `business` row already exists it raises `AlreadySeeded`.
- `python -m fixtures.seed` (`make seed`) catches that, prints "already seeded — run `make reseed` to start fresh", and exits 0, so re-running stays harmless.
- `python -m fixtures.seed --fresh` (`make reseed`) deletes the database file at `DATABASE_PATH` along with its `-wal` and `-shm` files, then migrates and seeds. Append-only events are never deleted row by row; the whole file is recreated instead.

**What the seed writes.** `business`, `party` and `bank_account` are not ledger tables, so they are inserted directly, along with `app_user` 1 with role owner (Q1). Every ledger row goes through the writer, with reason `"seed: TDD Part 1 worked example"` and source_ref `"fixture:seed"`:
- **3 vendor payables:** each is created with `create_payable` by actor `owner:1`, then moved to CONFIRMED with `transition` by `owner:1`.
- **GST:** `create_tax_obligation(GST, period 2026-09, due 2026-10-20, ₹90,000, CONFIRMED)` creates statutory payable GST-OCT26, which is then confirmed.
- **PF and ESI (Q2):** the recommendation is one PFESI-OCT26 payable, ₹45,000, due 2026-10-15, created through the first obligation. Two `tax_obligation` rows, PF and ESI, both ESTIMATED, link to that one payable.
- **Receivables:** Kaveri (COMMITTED, 13 Oct, ₹33,000) and Nandi (EXPECTED, 28 Oct, ₹2,00,000), each created with `create_receivable` by `owner:1`.

**Tests assert:**
- The same 5 payables and 2 receivables as before, so the golden numbers are unchanged, all CONFIRMED.
- The tax rows link to their payables through `payable_id` and carry the right `amount_status`.
- Each ledger row has its `*_CREATED` event, and each payable also has a `PAYABLE_CONFIRMED` event.
- A second `seed()` raises and leaves the event count unchanged.
- `--fresh` on an already-seeded file gives the same result as a first seed.

### D4 — write guard (`tests/test_ledger_write_guard.py`)

**What it scans.** The test AST-parses every `.py` file under `app/`, `fixtures/` and `evals/`. `tests/` is excluded, because tests legitimately poke tables (for example, the event-trigger test). It collects every string literal, including the literal parts of f-strings.

**What it matches.** The pattern is case-insensitive and spans whitespace and newlines:

`\b(INSERT(\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE(\s+OR\s+\w+)?|DELETE\s+FROM)\s+["`\[]?(payable|receivable|bank_txn|tax_obligation|event)\b`

**Exemptions.** `app/ledger/writer.py` is exempt. `app/db/migrations/*.sql` is too; it isn't `.py`, so it's never scanned. `ALLOW_LIST: dict[str, str]` maps a path to its reason and starts empty.

**Detector self-tests,** the same pattern as the clock guard:
- It flags a multi-line `INSERT INTO payable`.
- It flags `UPDATE OR IGNORE bank_txn`.
- It does not flag `SELECT * FROM payable`, `UPDATE job`, or `CREATE TRIGGER … BEFORE UPDATE ON event`.

**Known limit.** SQL whose table name is a runtime variable, such as `f"UPDATE {t}"` outside writer.py, is not caught; review still covers that case.

### D5 — Hypothesis stateful test (`tests/test_ledger_writer_stateful.py`)

A `RuleBasedStateMachine` runs each example on a fresh migrated temp DB, seeded with a business, owner 1 and one bank account.

**Rules:**
- `create_payable`, which creates a DRAFT bill.
- `attempt_transition`, with random inputs:
  - an existing payable;
  - a `to_state` from all 8 states;
  - an actor from {`owner:1`, `planner`, `reconciler`, `pipeline`, `agent:case:1`};
  - a correct or stale `expected_version`, plus a planned date when needed.
- `attempt_split`.

**Invariants, checked after every step:**
- The payable row count never decreases, and every id ever created still exists.
- A payable seen as PAID is only ever PAID or REOPENED from then on.
- Every successful call matches a row of `PAYABLE_TRANSITIONS` for the actor's role.
- Every refused call left the row's status and version unchanged and wrote no event.
- The event count equals the number of successful creates and transitions.

Settings: `max_examples=50`, `stateful_step_count=30`, which keeps `make test` under about 10 s.

### D7
Add a contract to `pyproject.toml`: "ledger never imports ai, agent, web or ingest", with `source_modules=["app.ledger"]` and `forbidden_modules=["app.ai","app.agent","app.web","app.ingest"]`.

To verify it, I'll temporarily add `import app.ai` to writer.py, watch lint-imports fail, then revert. That temporary import is never committed.

### Steps (CHG-002)
- [ ] S1 `domain/money.py`. Tests: golden strings, the TypeError cases, the Hypothesis round-trip.
- [ ] S2 `domain/states.py`. Tests:
  - the payable table equals the Part 2 rows exactly, and the D2 rows are present;
  - `parse_actor` accepts the four forms and refuses `agent:*` and malformed actors.
- [ ] S3 `domain/models.py`. Tests: float paise, unknown enum values and amounts ≤ 0 are all rejected.
- [ ] S4 `ledger/writer.py`: `atomic()` and the four `create_*` functions. Tests:
  - each create writes its row plus exactly one event (a tax obligation writes two: the obligation's and its payable's);
  - agent actors are refused;
  - an owner actor must be a real owner of that business.
- [ ] S5 `transition()` for payables. A parametrised matrix covers every (from, to, role): allowed moves succeed, and everything else is refused. Each success bumps the version by one and writes exactly one event with before and after.
- [ ] S6 Rollback tests: an event-insert failure, and the nested `atomic()` case.
- [ ] S7 Optimistic locking. Tests: an owner call without `expected_version` is refused; a stale version is refused and nothing is written.
- [ ] S8 Transition fields. Tests:
  - PLANNED needs `planned_date`, and WAIT clears it;
  - PAYMENT_EXPECTED sets approved_by and approved_at from the actor and the Clock;
  - a disallowed field is refused.
- [ ] S9 bank_txn and receivable transitions (D2). Tests: each cited row works, uncited rows are refused, and agent actors are refused.
- [ ] S10 `split_payable`. Tests:
  - the parent moves to SPLIT, both children carry `parent_payable_id`, and their amounts sum to the parent's;
  - 3 events are written;
  - a non-owner, wrong state, bad amounts or stale version is refused.
- [ ] S11 The D5 stateful test.
- [ ] S12 D3: seed through the writer, plus `--fresh` and `make reseed`. Tests: updated `tests/test_seed.py`.
- [ ] S13 D4 write guard and detector self-tests. This fails at the start commit, because the old seed's raw INSERTs are still there.
- [ ] S14 The D7 contract and the verified violation.
- [ ] S15 Add `make reseed` to CLAUDE.md's Commands section, then gate.

---

## CHG-003 — Planner

### Program design

```
 app/planner/
+  plan.py      # NEW — PlanSnapshot & input types (TDD block), PlanResult, plan(), canonical_json()
+  forecast.py  # NEW — project(opening, movements, days) -> daily balances; opening_cash(accounts)
+  options.py   # NEW — options(snapshot, result) -> list[OptionResult]
+  diff.py      # NEW — diff(old, new) -> PlanDiff
~ app/db/read.py   # MODIFIED — build_snapshot(conn, business_id, today) -> PlanSnapshot
+ tests/test_planner_forecast.py  test_planner_targets.py  test_planner_golden.py
+ tests/test_planner_options.py  test_planner_properties.py  test_planner_determinism.py
+ tests/test_planner_diff.py  test_snapshot_builder.py
```

**Where the snapshot builder lives.** The TDD layout has no slot for it, and `planner` may not touch the DB. It goes in `db/read.py` ("read-only queries") and uses a read-only connection. `db` importing `planner` types is allowed; no contract forbids it.

**Out of scope, flagged:**
- persisting `plan_run`, `plan_line`, `plan_day` and `shortfall_option`;
- applying the planner's CONFIRMED↔PLANNED moves.

Both belong to the `replan` and `monday_plan` jobs, and **no backlog entry owns them yet**. I propose a new draft entry, CHG-013 "Replan job: persist plan runs, apply planner transitions", sequenced before CHG-006.

**Types** (TDD field names kept; additions marked):

```python
@dataclass(frozen=True)
class AccountCash:  account_id: int; calculated_paise: int; reported_paise: int | None; drift_unresolved: bool
@dataclass(frozen=True)
class PayableIn:    payable_id: int; amount_paise: int; due_date: date; priority: Priority; grace_days: int
                    discount_paise: int | None; discount_by: date | None
                    status: Literal["CONFIRMED","PLANNED","REOPENED","PAYMENT_EXPECTED"]; planned_date: date | None
@dataclass(frozen=True)
class InflowIn:     receivable_id: int; amount_paise: int; expected_date: date; confidence: Literal["COMMITTED","EXPECTED"]
@dataclass(frozen=True)
class CommitmentIn: commitment_id: int; day: date; amount_paise: int; label: str     # D1: kept; builder passes ()
@dataclass(frozen=True)
class PlanSnapshot: today; horizon_days; payment_days: frozenset[int]; safety_paise; accounts; payables; inflows; commitments
                    uncounted_inflows: tuple[InflowIn, ...]   # ADDITION (Q3): EXPECTED any date + COMMITTED after the horizon

@dataclass(frozen=True)
class Movement:   day: date; amount_paise: int; source: Literal["inflow","commitment","payment_expected","bill"]; ref_id: int
@dataclass(frozen=True)
class DayBalance: day: date; balance_paise: int
@dataclass(frozen=True)
class PlanLine:   payable_id: int; decision: Literal["PAY","WAIT","ESCALATE"]; pay_on: date | None; amount_paise: int; reason: str
@dataclass(frozen=True)
class PlanResult: opening_cash_paise; safety_paise; days: tuple[DayBalance, ...]      # full schedule (step 4) — what plan_day stores
                  movements: tuple[Movement, ...]; lines: tuple[PlanLine, ...]       # lines sorted by payable_id
                  lowest_balance_paise; lowest_on; breach_on: date | None; gap_paise: int; valid: bool
```

**Algorithm.** Each rule is pinned to a TDD step. Where I've had to interpret, the interpretation is stated here so the golden test and properties lock it.

1. **Horizon.** `today … today + horizon_days − 1`, which gives 12–25 Oct, 14 days.
2. **Opening cash.** The sum over all accounts. For an account with `drift_unresolved` and a non-null `reported_paise`, use `min(calculated, reported)`; otherwise use `calculated`.
3. **Base curve.** Start from opening cash, add `inflows` dated in the horizon (COMMITTED only, by type), and subtract `commitments` in the horizon. Then subtract PAYMENT_EXPECTED bills:
   - On their `planned_date`.
   - On **today** if that date is before today or null. This is conservative: we haven't seen the money leave yet.
   - Not at all if the date is after the horizon.
   - PAYMENT_EXPECTED bills get **no plan line**, because they're already approved and there's no decision left to make.
4. **Target day** for each CONFIRMED, PLANNED or REOPENED bill:
   - (a) Take the due date. Use `discount_by` instead when `discount_paise > 0` and a payment day exists in `[today, discount_by]` (Q4).
   - (b) Target the latest payment day `d` with `today ≤ d ≤` that date.
   - (c) **Overdue rule.** If there is no such day, either because the bill is overdue or because no payment day falls between today and its due date, target the **next payment day on or after today. Today counts if it is a payment day.**
   - (d) **WAIT.** If the target is after the horizon end, or there is no payment day at all, the line is WAIT. The reason is "due <date>, after the planning horizon (ends <date>)" or "no payment day in the horizon".

   So bills due after the horizon get WAIT. PLANNED bills are re-targeted from scratch and their `planned_date` is ignored.
5. **Full schedule.** The base curve minus every non-WAIT bill on its target day. This gives:
   - `days`;
   - `lowest_balance_paise`, and `lowest_on` (the earliest day holding the minimum);
   - `breach_on`, the first day below safety, or None.
6. **Placement.** Bills are placed in priority order (statutory, critical, normal, flexible), then by due date, then by id, against a running curve that starts as the base curve.
   - **PAY:** a bill gets PAY if every day from its target onward stays at or above safety once it is subtracted. It is then subtracted from the running curve.
   - **Statutory:** statutory bills always get PAY. If one causes a breach, its reason says so and the plan's validity catches it.
   - **ESCALATE:** any other bill that would breach gets ESCALATE and is not subtracted.
     - Its `breach day` is the first day from its target onward that falls below safety.
     - Its `gap` is safety minus the lowest balance from its target onward.
     - The exact reason text is: `Paying ₹1,20,000 on Thu 22 Oct takes the balance below the safety amount from Thu 22 Oct: lowest ₹1,83,000 on Thu 22 Oct, ₹67,000 below.`
7. **Validity.** A plan is valid when nothing is escalated **and** every day of the full schedule is at or above safety. The second half covers breaches caused by statutory bills, and a base curve that is already below safety (for example, opening cash below safety with no bills at all). That keeps "a normal plan never projects below safety" true without exception.

**Options.** `options()` returns `[]` when the plan is valid. Otherwise options come in kind order (early_receipt, split, delay_flexible, authorise_breach, ask_ca), then by id. Each option that has numbers is `plan()` re-run on a changed snapshot, with `meets_rule = rerun.valid` and `lowest_*` taken from the re-run's full schedule.

- **early_receipt (D6).** Offered for every receivable in `inflows ∪ uncounted_inflows` dated after `breach_on`.
  - Let `P` be the last payment day strictly before `breach_on`, and `W` the last weekday (Mon–Fri) strictly before `P`.
  - The receivable moves to `W` and is counted.
  - Not offered if `P` or `W` is before today, since you can't ask for money in the past.
  - Worked example: breach Thu 22 → P = Mon 19 → W = Fri 16.
  - Params: `{receivable_id, amount_paise, from_date, to_date}`.
- **split.** Offered for every ESCALATE bill with `amount − gap > 0`.
  - Part 1 is `amount − gap`, keeps the same id and the same due date.
  - Part 2 is `gap`, due on horizon end + 1 day, with the synthetic id `−payable_id`, so it gets WAIT.
  - Params: `{payable_id, pay_now_paise, rest_paise, rest_due}`.
  - Worked example: 53,000 now and 67,000 due 26 Oct. The re-run's lowest is ₹2,50,000 on 22 Oct, which meets the rule exactly.
- **delay_flexible.** Offered for every flexible bill with `grace_days > 0` and a non-WAIT target.
  - The re-run uses `due_date + grace_days`, which gives the latest payment day within the grace period.
  - Params: `{payable_id, from_date, to_date}`.
- **authorise_breach.** Always offered when the plan is invalid.
  - No re-run: the lowest balance is `r.lowest` and `meets_rule=False`.
  - Params: `{gap_paise, lowest_on}`.
- **ask_ca.** Offered if a re-run with every non-statutory payable removed is still invalid. It carries no numbers (`lowest_balance_paise=None`, `meets_rule=False`).

**diff.py** (later consumed by `explain_plan`):

```python
@dataclass(frozen=True)
class Change:   kind: Literal["opening_cash","lowest","validity","line_added","line_removed","line_changed"]
                payable_id: int | None; before: dict | None; after: dict | None   # dicts of ints, ISO dates, decisions
@dataclass(frozen=True)
class PlanDiff: changes: tuple[Change, ...]        # summary kinds first (in that order), then lines by payable_id
                amounts_paise: frozenset[int]      # every amount mentioned in changes — the explain check's allow-list
                dates: frozenset[date]             # every date mentioned
def diff(old: PlanResult, new: PlanResult) -> PlanDiff
```

The golden diff compares the worked-example plan with the early-receipt re-run. It should show exactly:
- lowest balance: 18,300,000 on 2026-10-22 → 38,300,000 on 2026-10-22;
- validity: False → True;
- Prime Chem: ESCALATE → PAY on 2026-10-22.

**Determinism.**
- `canonical_json(result) -> bytes` uses sorted keys, ISO dates and ints only.
- One test calls `plan()` twice and compares the bytes.
- A second test runs the golden in two subprocesses, one with `PYTHONHASHSEED=1` and one with `=2`, and compares the bytes. This catches any set or dict iteration order leaking into the output.

### Contracts consumed — snapshot inputs

The producer is CHG-002's schema (`0001_init.sql`, transcribed from TDD Part 2 in batch 0) and writer, read through `build_snapshot`. In the Cite column, **code** means the producing schema or writer code, driven by a test in this batch, and **doc** means TDD text only.

| Input → field | 1. Units / scale | 2. Empty | 3. Absent | 4. Failure | Cite |
|---|---|---|---|---|---|
| `business.safety_amount_paise` → `safety_paise` | int paise, CHECK ≥ 0 | 0 → valid, no floor | NOT NULL; no business row → `build_snapshot` raises `LookupError` | sqlite error propagates; no partial snapshot | code |
| `business.horizon_days` → `horizon_days` | int days, counted including today (12–25 Oct = 14) | 0 or negative → builder raises `ValueError` (no CHECK in schema) | NOT NULL DEFAULT 14 | as above | code + doc (worked example) |
| `business.payment_days` → `payment_days` | TEXT, comma-separated `MON..SUN` → frozenset 0=Mon..6=Sun | `''` → empty set → all bills WAIT "no payment day in the horizon" | NOT NULL DEFAULT 'MON,THU' | unknown token (`MONDAY`, `mon`) → `ValueError`, never silently drop a day | code (schema default) — token set is ours |
| `account_balance.calculated_balance_paise` → `calculated_paise` | int paise; opening + credits − debits with `txn_date ≥ opening_balance_at`, excluding REVERSED | no txns → `opening_balance_paise` (COALESCE 0) | every account has a view row (LEFT JOIN, GROUP BY a.id); no accounts → `accounts=()` → opening cash 0 | as above | code (view SQL) |
| `bank_account.reported_balance_paise` → `reported_paise` | int paise, nullable | 0 → a real zero report; `min(calc, 0)` applies under drift | NULL → calculated is used even under drift | — | code |
| `bank_account.drift_status` → `drift_unresolved` | `OK`/`CHECKING`/`ASK_OWNER` (CHECK) | n/a | NOT NULL DEFAULT 'OK' | unresolved = `≠ 'OK'` | code + doc ("While an account is not OK … the lower of its two balances") |
| `payable` rows → `payables` | `amount_paise` int > 0 (CHECK); dates ISO TEXT → `date`; status ∈ {CONFIRMED, PLANNED, REOPENED, PAYMENT_EXPECTED} (DRAFT, REVIEW, PAID, SPLIT excluded) | no rows → `payables=()` → no lines, base curve only | `due_date` NOT NULL; `planned_date` NULL → see algorithm step 3; `discount_*` NULL → no discount | malformed date string → `ValueError` (no partial snapshot); `grace_days < 0` (no CHECK) → `ValueError` | code + doc (Planning engine type comment) |
| `payable.discount_paise` / `discount_by` | **Q4**: read as "paise saved if paid by `discount_by`"; amount paid = `amount − discount` | 0 → no discount | NULL → no discount | `discount_paise ≥ amount` → `ValueError` | **question** (schema has no comment) |
| `receivable` rows → `inflows` | COMMITTED with `expected_date` inside the horizon; `amount_paise` int > 0 | none → `inflows=()` | `expected_date` NULL → not counted and not offered (no date to move) | malformed date → `ValueError` | code + doc (decisions log: "Only COMMITTED receivables count") |
| `receivable` rows → `uncounted_inflows` (Q3) | EXPECTED with a date, plus COMMITTED dated after the horizon; CONFIRMED (already in bank) and UNKNOWN excluded | none → `()` → no early_receipt option | as above | as above | doc (Shortfall options table: "A COMMITTED or EXPECTED receivable is dated after the breach") |
| COMMITTED dated **before** today | — | — | — | not counted (the promise date passed without a matched credit); not offered | ours, stated here |
| `commitments` | int paise | always `()` in MVP (D1) | n/a | n/a | PO D1 |
| `today` | `date` in Asia/Kolkata, from the caller's `Clock.today()` | n/a | required argument | n/a | code (`app/clock.py`) |

Each row with a non-trivial empty, absent or failure answer gets a test in `test_snapshot_builder.py`, driving the real SQL against a real migrated DB.

### Fixture sources
- **Golden, seed and options.** Every amount, date, priority, confidence and expected figure comes from TDD Part 1, "Worked example". The only values not taken from that table are these:
  - The party names, which are fictional and come from batch 0's seed.
  - The tax periods. Both use `2026-09`: GST is GSTR-3B for September, due 20 Oct, and PF/ESI is for September wages, due 15 Oct. These follow standard Indian due-date conventions and match the worked example's due dates.
  - The PF/ESI amount split (Q2).
- **Hypothesis snapshots.** Amounts range from 1 to 10⁹ paise (up to ₹1 crore). Dates fall in `[today − 20, today + horizon + 20]`, so they cover overdue bills, bills inside the horizon and bills after it.

### Steps (CHG-003)
- [ ] T1 `plan.py` types and `forecast.py` (`opening_cash`, `project`). Tests: projection arithmetic, and the lower-of rule under drift.
- [ ] T2 Target-day rules. Tests:
  - the latest payment day on or before the due date, and never before today;
  - an overdue bill goes to the next payment day, with today included;
  - no payment day between today and the due date → the next payment day;
  - a target after the horizon → WAIT;
  - empty `payment_days`;
  - discounts (Q4).
- [ ] T3 Base curve. Tests:
  - PAYMENT_EXPECTED is subtracted on its `planned_date`, or on today if that date is past or null;
  - PAYMENT_EXPECTED gets no line;
  - inflows outside the horizon are ignored.
- [ ] T4 Placement, decisions, reasons and validity.
  - Golden test: 14 balances; 5 lines with exact reasons; ₹1,83,000 on 22 Oct; breach on 22 Oct; gap ₹67,000; `valid=False`.
  - Unit tests: a statutory breach still gets PAY and makes the plan invalid; a base curve already below safety is invalid.
- [ ] T5 `canonical_json` and the determinism tests, including the subprocess hash-seed check.
- [ ] T6 `options.py`.
  - Golden: exactly 3 options with the Part 1 figures, and the Nandi re-run's 14 balances equal Part 1's second column.
  - Unit tests:
    - early_receipt is not offered when P or W is in the past (**the AC5 lock for D6**);
    - delay_flexible;
    - ask_ca;
    - a split with gap ≥ amount is not offered.
- [ ] T7 Hypothesis invariants (AC2).
- [ ] T8 `diff.py`. Tests:
  - the golden diff;
  - the `amounts_paise` and `dates` sets equal exactly what appears in the changes;
  - identical plans give an empty diff.
- [ ] T9 `build_snapshot` and the contract-row tests.
- [ ] T10 End-to-end. `seed()` → `build_snapshot(today=2026-10-12)` → `plan()` → `canonical_json` must equal the golden bytes from the hand-built snapshot. This proves the seed, builder and planner agree. Then gate.

**Hypothesis invariants (CHG-003 AC2, revised).** "PAID never disappears" has moved to CHG-002 AC5 (D5), because the planner never sees PAID bills.
- **I1** If the plan is valid, every balance in `days` is at or above safety.
- **I2** Every rupee traces to a record. `days[i] = opening + Σ movements dated ≤ days[i]`, and every movement's `ref_id` and amount match a snapshot record.
- **I3** Opening cash uses the lower balance under drift. Lowering a drifted account's `reported_paise` never raises opening cash.
- **I4** Statutory bills never get ESCALATE. Every PAY falls on a payment day within `[today, horizon end]`. WAIT is given exactly when no target exists in the horizon.
- **I5** Every CONFIRMED, PLANNED or REOPENED payable gets exactly one line; PAYMENT_EXPECTED gets none.
- **I6** Each option's `meets_rule` equals its re-run's `valid`.
- **I7** Every amount in the output is an `int`, never a `bool` or `float`.

---

## Questions for PO

Each question blocks, but each has a recommended default. If you approve the plan as written, I'll use the defaults.

| # | Question | Recommendation |
|---|---|---|
| Q1 | Who is the seed's actor? `owner:<id>` must be a real owner `app_user`, and the seed creates none today. | The seed inserts `app_user` 1 (`owner@example.test`, role owner). Its `password_hash` is the sentinel `"!seed: no login until CHG-006"`, which can never verify. Seed events read `owner:1`, with reason `"seed: TDD Part 1 worked example"`. The alternative is a new `seed` actor, which isn't in the TDD. |
| Q2 | PF and ESI are one ₹45,000 line in the worked example. But `tax_type` holds one value, and the TDD says "each tax obligation creates a statutory payable". | Keep **one** PFESI payable, so the golden is untouched, and add **two** `tax_obligation` rows (PF, ESI), both ESTIMATED and linked to it by `payable_id`. Their split isn't in the TDD: give me figures, or approve ₹36,000 PF / ₹9,000 ESI, marked fixture-invented in a comment. |
| Q3 | `early_receipt` needs EXPECTED and out-of-horizon receivables, but the TDD's `inflows` comment limits that field to COMMITTED receivables inside the horizon. Nandi is EXPECTED, 28 Oct. This is an inconsistency within Part 2. | Add `PlanSnapshot.uncounted_inflows`, and keep `inflows` exactly as the TDD comment defines it. |
| Q4 | The units of `discount_paise` aren't specified, and nothing says what happens when an early-discount payment would breach. | Read `discount_paise` as the paise saved if paid by `discount_by`; the planner pays `amount − discount`. There is no fallback to the due-date target, so the bill gets ESCALATE as usual. The worked example has no discounts. |
| Q5 | Three bank_txn moves aren't in the TDD. (a) UNMATCHED→EXPLAINED: by the owner (answering `explain_txn`), by the reconciler (applying a code-verified RESOLVED answer from the agent), or both? (b) UNMATCHED→MATCHED by the owner, when they resolve a REVIEW bill as paid? (c) UNMATCHED→REVERSED? | Defer all three to CHG-005 (reconciliation), where their callers will exist. They are refused until then. |
| Q6 | Three receivable moves aren't in the TDD: the owner re-rating among COMMITTED/EXPECTED/UNKNOWN; creation by `pipeline`; any move out of CONFIRMED. | Defer to CHG-005/CHG-006; refused until then. The seed only needs creation by the owner. |
| Q7 | The TDD doesn't name the payable creation actors (pipeline, owner) or the start state of split children. | Creation is DRAFT, by `pipeline` or `owner`. Split children start CONFIRMED: the owner's split is itself a confirmation, and Part 1 says each part "follows the same states". |
| — | A flag rather than a question: no backlog entry owns the replan and monday_plan jobs, which persist plan runs and apply PLANNED↔CONFIRMED. | Add a new draft, CHG-013, sequenced before CHG-006. |
