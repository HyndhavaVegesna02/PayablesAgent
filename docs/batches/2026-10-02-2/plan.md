# Batch 2 — Plan

**Covers:** CHG-013 (worker and replan), CHG-004 (alert ingestion) and CHG-005 (reconciliation). All three are `planned`.

**Branch:** `batch-2`, cut from `main` at acaac9b.

**Order:** 013 → 004 → 005.
- 004's pipeline runs as jobs inside 013's worker.
- 005's handlers are queued by 004 and use 013's replan.

I'll work inline and sequentially, because the expected paths overlap (`app/worker.py`, `app/jobs/`, `fixtures/seed.py`).

**Exit (TDD Phase 4).** Three things must work:
- A test-inbox debit alert reconciles against a payment approved through the planner, and the bill becomes PAID.
- A return email gives REOPENED, a REVERSED debit, and a replan.
- A missing alert gives CHECKING.

The web app doesn't exist yet, so in tests the owner's approval is a `writer.transition` call.

**Router:**
- **CHG-013 → `planned`.** Trigger: it consumes a contract it didn't write (APScheduler's CronTrigger semantics and timezone, and CHG-003's `PlanResult` and options mapped onto the plan tables).
- **CHG-004 → `planned`, the cap.** Trigger: it consumes the Gemini SDK and API, plus RFC 2822 email headers.
- **CHG-005 → `planned`, the cap.** Trigger: it consumes CHG-004's extracted-transaction contract (nullable counterparty, reference and balance).

**Standing policies (PO):**
- No live Gemini call in `make test` or in any default path. Tests use a fake backend.
- The one live target, `make smoke-gemini`, is planned here but not run until the PO authorises it.
- Never touch `.env`.
- No Gmail or OAuth code. MailSource uses only the test inbox.
- Local `make test` through `yt_gate.py` is the gate.

**Dependencies.** None are added. The lock already pins `google-genai` 2.27.0 and `apscheduler` 3.11.3, and `httpx` is a dev dependency for offline SDK error tests. Under R002, no pin changes in this batch.

---

## Intent

After this batch, the loop runs on its own against the test inbox:
1. The worker polls the inbox.
2. Gemini (faked in tests) sorts and extracts a bank alert. Code validates it, and the pipeline writes it to the ledger.
3. The reconciler matches it to the bill the owner approved.
4. The planner re-plans and persists the new plan.

Failures and return emails reopen bills. A balance that doesn't add up puts the account into CHECKING. Every AI call leaves a trace line with tokens and cost.

**How to see it worked:**
- `make test` passes, including `tests/test_phase4_exit.py`, which runs the three exit scenarios end to end through the real worker on the seeded database.
- `python -m app.trace.view job-<id>-attempt-1` prints the sort, extract and validate steps for the debit alert.

---

## CHG-013 — Worker, replan, monday_plan, persisted plans

### Program design

```
+ app/worker.py               # NEW — job runner loop, handler registry, heartbeat, scheduler setup, `python -m app.worker`
+ app/jobs/replan.py          # NEW — enqueue_replan() (absorbs duplicates), handle_replan, handle_monday_plan, persist_plan()
~ app/jobs/queue.py           # MODIFIED — mark_failed(..., permanent=True) dead-letters at once
~ app/ledger/writer.py        # MODIFIED — set_planned_date() for a PLANNED bill whose pay date moves (Q5)
~ app/planner/plan.py         # MODIFIED — PLANNER_VERSION constant
~ app/main.py                 # MODIFIED — /api/health reports the worker heartbeat
~ fixtures/seed.py            # MODIFIED — DATABASE_PATH via Settings; clear error on a locked DB with --fresh (PO fold-in)
~ Makefile                    # MODIFIED — `make worker` runs the worker
~ CLAUDE.md                   # MODIFIED — make worker no longer a stub
+ tests/test_worker.py  test_replan.py  test_scheduler.py
~ tests/test_health.py  tests/test_seed.py  tests/test_jobs_queue.py
```

**Worker loop:**

```python
Handler = Callable[[JobContext], None]          # JobContext: conn, job row, payload dict, clock, tracer, settings, app_config
def process_one(conn, handlers: Mapping[str, Handler], *, clock, settings, app_config) -> bool:
    job = claim_one(conn, kinds=sorted(handlers), clock=clock); conn.commit()   # only kinds with a handler are claimed
    if job is None: return False
    tracer = Tracer(f"job-{job['id']}-attempt-{job['attempts'] + 1}", settings.trace_dir, clock)
    try:   handlers[job["kind"]](ctx); mark_done(conn, job["id"]); conn.commit()
    except PermanentJobError as e:  conn.rollback(); mark_failed(conn, id, str(e), permanent=True); conn.commit()
    except Exception as e:          conn.rollback(); mark_failed(conn, id, repr(e), retry_at=now + backoff(attempts)); conn.commit()
    return True
backoff(n) = min(30s * 2**(n-1), 1h)
def run(settings, app_config, clock=SystemClock(), *, stop: threading.Event): heartbeat file each loop; idle sleep 1s
```

- **Q10:** jobs whose kind has no handler yet, such as `run_case` before CHG-008, stay `queued`. They are never dead-lettered.
- **Heartbeat (Q1):** `DATA_DIR/worker.heartbeat` holds `clock.now().isoformat()`. `/api/health` reports `{"worker": {"last_heartbeat": iso | null}}`.

**Scheduler.** APScheduler's `BackgroundScheduler(timezone=Asia/Kolkata)` registers two triggers:
- a cron trigger, `day_of_week='mon', hour=7, minute=0`, which enqueues `monday_plan` with idempotency key `monday_plan:<date>`;
- an interval trigger every `mail.poll_minutes`, which enqueues `poll_mail`.

`schedule_jobs(scheduler, app_config)` is a pure registration. A test asks the trigger for `get_next_fire_time(None, clock.now())` with a FakeClock and expects Mon 07:00 IST. That is how scheduling reads time through the Clock.

**Replan:**
- `enqueue_replan(conn, business_id, triggered_by)` absorbs duplicates. If a `replan` job for that business is still `queued`, it returns that job's id instead of adding a new one.
- `handle_replan` / `handle_monday_plan` (with `triggered_by='monday'`) run inside one `writer.atomic(conn)`:
  1. Build the snapshot, then run `plan()` and `options()`.
  2. Insert `plan_run`:
     - `inputs_sha256 = sha256(canonical_json(snapshot))`;
     - `planner_version = PLANNER_VERSION`;
     - `is_current = 1`, with the previous current run cleared in the same transaction.
  3. Insert `plan_line`, `plan_day` and `shortfall_option` rows. `params_json` is canonical. Lines with a synthetic id (≤ 0) are never written.
  4. Apply state moves through the writer as `planner`:

| Line decision | Bill status | Writer call |
|---|---|---|
| PAY | CONFIRMED or REOPENED | `transition(→ PLANNED, planned_date=pay_on)` |
| PAY | PLANNED, different date | `set_planned_date` (Q5) |
| PAY | PLANNED, same date | nothing |
| WAIT or ESCALATE | PLANNED | `transition(→ CONFIRMED)` (Q6) |
| WAIT or ESCALATE | CONFIRMED or REOPENED | nothing |

  5. The event reason is the line's reason plus " Projected minimum ₹X on <day>; safety amount ₹Y; rule check PASSED|FAILED". PASSED means the full schedule never goes below safety from `pay_on` onward. This mirrors Part 1's example event.
  6. `source_ref` is `plan_run:<id>`. `trace_run_id` is the job's run id.
- **Out of scope:** `explain_plan` and `send_alert` are not enqueued yet. Neither has a handler; see Q9 and the new draft CHG-018.

### Contracts consumed

| Input | 1. Units / scale | 2. Empty | 3. Absent | 4. Failure | Cite |
|---|---|---|---|---|---|
| APScheduler CronTrigger | wall-clock fields in the given tz (Asia/Kolkata), not UTC | n/a | `get_next_fire_time` returns None when no further fire | a scheduler-thread exception is logged by APScheduler, the job loop is unaffected | doc (APScheduler 3.11 CronTrigger) + test asserting next fire |
| `PlanResult.lines` | int paise, ISO dates | `()` → no plan_line rows | `pay_on` None for WAIT and ESCALATE → stored NULL (nullable column) | n/a (pure) | code (CHG-003 plan.py) |
| `options()` | `params` ints and ISO strings | `[]` → no shortfall_option rows | `lowest_balance_paise` None (ask_ca) → NULL | n/a | code (options.py) |
| synthetic ids in what-ifs | `-payable_id` | — | — | never persisted; option plans aren't stored as plan_line | code (options.py split) |
| `job.payload_json` | JSON object | `{}` → handler uses defaults (business 1) | malformed JSON → `PermanentJobError` → dead | — | code (queue.py) |

### Acceptance criteria (CHG-013)
- AC1: The worker claims one queued job, dispatches it by `kind`, and marks it done. A failing handler is retried with exponential backoff and dead-lettered after `max_attempts`. A `PermanentJobError` dead-letters at once. A kind with no handler stays queued.
- AC2: A replan persists `plan_run` (with `inputs_sha256`, `planner_version` and `is_current`), plus `plan_line`, `plan_day` and `shortfall_option`. Exactly one run per business is current.
- AC3: A replan on the seeded worked example persists:
  - the 14 golden balances;
  - lines with 4 PAY and 1 ESCALATE;
  - 3 options.

  It moves the 4 PAY bills to PLANNED and leaves Prime Chem CONFIRMED. Each move goes through the writer as `planner`, with the Part 1-style reason.
- AC4: A second replan whose decision for a PLANNED bill turns to WAIT or ESCALATE moves it back to CONFIRMED, and a changed pay date updates `planned_date` with an event.
- AC5: Two replan requests made while one is still queued result in one job.
- AC6: `monday_plan` is scheduled for Mon 07:00 Asia/Kolkata. With the FakeClock, the next fire time is computed correctly, and the job runs a replan with `triggered_by='monday'`.
- AC7: `/api/health` reports the worker's last heartbeat. `make worker` runs the loop instead of failing.
- AC8: The seed reads `DATABASE_PATH` through `Settings`. `--fresh` on a locked DB file exits with a clear message instead of a traceback (PO fold-in).

### Steps (CHG-013)
- [ ] W1 `queue.mark_failed(permanent=True)` plus its test.
- [ ] W2 `worker.process_one`, covering done, retry with backoff, dead-letter, permanent errors and unregistered kinds. Tests use real SQLite, a FakeClock and stub handlers.
- [ ] W3 Heartbeat file and the `/api/health` change. Update `test_health`.
- [ ] W4 `schedule_jobs` and its trigger tests.
- [ ] W5 `writer.set_planned_date`. Tests: planner only, PLANNED only, version bump plus event, agent refused.
- [ ] W6 `replan.persist_plan` and `handle_replan` on the seeded DB: golden persisted, state moves, events, is_current flip, synthetic ids skipped.
- [ ] W7 Re-plan transitions (PLANNED→CONFIRMED, date move) and `enqueue_replan` absorption.
- [ ] W8 `monday_plan` handler, `python -m app.worker` entry, Makefile, CLAUDE.md.
- [ ] W9 Seed reads Settings and handles a locked file. Then gate.

---

## CHG-004 — Alert ingestion (test inbox, ai.client, sort, extract, validate)

### Program design

```
+ app/ingest/mail_source.py    # NEW — MessageRef, RawMessage, MessageSummary, MailSource Protocol (Part 2, verbatim)
+ app/ingest/eml_folder.py     # NEW — EmlFolderSource(path, clock): list_new / fetch / search
+ app/ingest/store.py          # NEW (Q8) — Fernet encrypt/decrypt of stored documents under DATA_DIR
+ app/ingest/pipeline.py       # NEW — handle_poll_mail, handle_process_document (sort → extract → validate → route)
+ app/ai/client.py             # NEW — call(): the one function that calls Gemini; Backend seam; GeminiBackend; FakeBackend lives in tests
+ app/ai/sort.py  extract.py   # NEW — SortResult, BankAlertExtract, FailureNoticeExtract + prompt loading
+ app/ai/prompts/sort.v1.md  extract_bank_alert.v1.md  extract_failure.v1.md   # NEW — versioned prompts
+ app/ai/smoke.py              # NEW — `make smoke-gemini`: ≤ 3 live calls, opt-in, NOT run by the batch
+ app/validate/__init__.py  dates.py  duplicates.py  alert.py   # NEW — the rule checks a bank alert needs (Q3)
~ app/domain/money.py          # MODIFIED — parse_inr(text) -> paise (strict; Q4)
~ app/trace/tracer.py          # MODIFIED — redact fields *named* password/token/key, not every name containing them ("tokens" was being blanked)
~ app/config.py  config.yaml   # MODIFIED — model.pricing (integer micro-USD per 1M tokens, Q2), ai.timeout_ms
~ fixtures/seed.py             # MODIFIED — HDFC account alert_senders_json = ["alerts@hdfcbank.example"]
+ fixtures/test_inbox/*.eml    # NEW — fictional HDFC-style alerts (see Fixture sources)
~ Makefile                     # MODIFIED — smoke-gemini target
+ tests/conftest.py            # NEW — autouse: block non-loopback socket connects (no network in make test)
+ tests/fake_ai.py             # NEW — FakeBackend: canned text + usage_metadata, records every request
+ tests/test_ai_client.py  test_eml_folder.py  test_pipeline.py  test_validate_alert.py  test_money.py(~)  test_tracer.py(~)
```

**`ai.client`.** This is the only module that imports `google.genai`. An import-linter contract enforces that.

```python
class Backend(Protocol):
    def generate(self, *, model: str, system: str, contents: str, config: GenerationRequest) -> RawAIResponse: ...
@dataclass(frozen=True) class AIResult: text: str; parsed: BaseModel | None; input_tokens: int; output_tokens: int; thought_tokens: int; cost_micro_usd: int
class AIUnavailable(Exception): retryable: bool; code: int | None; status: str | None
def call(*, job: str, thinking: ThinkingLevel, system: str, context: str, schema: type[BaseModel] | None,
         backend: Backend, app_config: AppConfig, tracer: Tracer, input_ref: str) -> AIResult
```

- The thinking level is validated against `{"low","medium","high"}` by our code. "minimal" is refused, because the SDK accepts it but the server rejects it.
- The config is `types.GenerateContentConfig(system_instruction=..., thinking_config=types.ThinkingConfig(thinking_level=...), response_mime_type="application/json", response_json_schema=schema.model_json_schema())`. No temperature, top_p, top_k or thinking_budget is sent.
- Parsing is `schema.model_validate_json(r.text)` by our code. `r.parsed` and `response_schema=` are not used.
- Usage is `prompt_token_count or 0`, `candidates_token_count or 0` and `thoughts_token_count or 0`. Billed output is candidates plus thoughts.
- Cost is `ceil((in*in_rate + out*out_rate) / 1e6)` in integer micro-USD. The rates come from `config.yaml`: 750,000 and 3,750,000 micro-USD per 1M tokens.
- Each call writes one tracer step: input_ref, model, thinking, tool="ai.call:<job>", result (first 200 characters), validation, retries=0, tokens {input, output, thoughts}, cost.
- Error handling:
  - `google.genai.errors.ServerError`, a 429 `ClientError`, and httpx timeouts or transport errors all raise `AIUnavailable(retryable=True)`, so the job queue retries.
  - Any other `ClientError` raises `AIUnavailable(retryable=False)`, which the pipeline turns into `PermanentJobError`.
  - SDK retry stays off (the default), so attempts are 1 and backoff isn't doubled.
- `GeminiBackend(api_key)` refuses an empty key. It is built only by the worker or the smoke command from `Settings`, and never by tests.

**Pipeline (TDD "The pipeline for one document", steps 1, 3, 4, 5 and 6, scoped to alerts):**

```
handle_poll_mail: since = sync_state.last_synced_at − 1 day (or seed opening date)
  for ref in source.list_new(since, senders=all accounts' alert_senders_json):
    insert source_document (kind='email', external_ref=Message-ID, content_sha256, received_at, storage_path=encrypted file)
      — UNIQUE (business, sha) / (business, kind, external_ref) → already seen, skip
    enqueue process_document, idempotency_key=f"process_document:{doc_id}"
  update sync_state
handle_process_document(doc):
  1. sort  (ai.call job="sort", thinking=config.sort=low)  → irrelevant → doc IRRELEVANT, stop
  2. (unlock: not for alerts — statements are CHG-007)
  3. extract (job="extract", thinking=config.extract=medium, schema=BankAlertExtract | FailureNoticeExtract)
  4. validate → candidate row (record_type txn, payload_json, model_id, thinking, prompt_version, checks_json, attempts, created_by='pipeline')
     a failed check → re-extract once with the failed checks attached (attempt 2, medium)
  5. second failure → extract at high (attempt 3); still failing → candidate AWAITING_OWNER + owner_question confirm_record; stop
  6. route:  bank alert → writer.create_bank_txn(actor='pipeline', dedup_key built by code) → enqueue reconcile_txn {bank_txn_id, reported}
             failure / return email → enqueue reconcile_failure {candidate_id}
             other doc types (statement, invoice, challan, payment_confirmation) → doc PROCESSED with "handled in CHG-007"; no AI extract
```

**Extraction schema (Q4).**
- `BankAlertExtract` has these fields:
  - `account_last4: str`;
  - `direction: Literal['debit','credit']`;
  - `amount_text: str`, the amount exactly as written;
  - `txn_date: date`;
  - `counterparty: str | None`;
  - `reference: str | None`;
  - `available_balance_text: str | None`;
  - `uncertain_fields: list[str]`.
- Code turns the amounts into paise with `parse_inr`. The model never produces a number we store.
- `FailureNoticeExtract` has: `account_last4`, `amount_text`, `original_reference | None`, `failure_date`, `reason: str`, `uncertain_fields`.

**Rule checks for an alert (Q3).** Every candidate records each check in `checks_json` as `{name: "passed" | "failed: <why>" | "not_applicable"}`:
- schema (Pydantic);
- amount parses to positive int paise;
- account: the last 4 digits match an account of this business whose `alert_senders_json` contains the From address;
- dates: `txn_date` is on or before the email's Date and no more than 7 days before it;
- duplicates: the code-built `dedup_key` is not already in `bank_txn`;
- confidence: `uncertain_fields` is empty, otherwise the candidate goes to the owner.

GSTIN, invoice arithmetic and statement arithmetic are recorded `not_applicable` for alerts and land in CHG-007.

### Contracts consumed

| Input | 1. Units / scale | 2. Empty | 3. Absent | 4. Failure | Cite |
|---|---|---|---|---|---|
| `GenerateContentResponse.text` | JSON string per our schema | `""` → `model_validate_json` fails → counts as a failed schema check (retry ladder) | `None` (blocked, no candidate) → same as a failed schema check | — | code: SDK 2.27.0 `types.py` `.text` property, probed offline via MockTransport |
| `usage_metadata.*_token_count` | int tokens | 0 → 0 | `usage_metadata` None, or a field None → 0 (`or 0`) | — | code (SDK types, all Optional) + MockTransport test with fields omitted |
| SDK errors | `APIError.code` HTTP int, `.status` string | — | `.code` None → treated as retryable | ServerError 5xx / 429 → retryable; other 4xx → permanent; httpx.TimeoutException (not APIError) → retryable | code: `google.genai.errors` + MockTransport tests returning 429/500/400 and raising a timeout |
| `amount_text` | rupees as written: `Rs.1,80,000.00`, `INR 33,000`, `₹45,000.5` | `""` → check fails | `None` → schema check fails (required) | junk (`1.80 lakh`, `18O000`) → check fails, never guessed | ours: `parse_inr` strict grammar, tested |
| Email `Date` / `From` / `Message-ID` | RFC 2822 | — | `Date` missing → file mtime is not used; doc FAILED "no Date header". `Message-ID` missing → external_ref = sha256. `From` missing → skipped by `list_new` (sender filter) | malformed Date → doc FAILED | stdlib `email.utils.parsedate_to_datetime` (raises on bad input), tested |
| `available_balance_text` | rupees | — | None → no reported balance; no drift check | unparsable → check fails | ours |

### Acceptance criteria (CHG-004)
- AC1: A sample HDFC-style debit alert in the test inbox becomes a `bank_txn` row end to end through the worker: poll → source_document → sort → extract → validate → `writer.create_bank_txn` → `reconcile_txn` queued. The fake AI returns canned responses.
- AC2: The run leaves a readable trace. `python -m app.trace.view job-<id>-attempt-1` shows the sort and extract calls with model, thinking level, tokens and cost, plus the validation result. Fields named `tokens` are not redacted.
- AC3: Extraction uses structured output with `response_json_schema` from the Pydantic model, and our code parses `r.text`. An offline MockTransport test asserts the outgoing request carries `thinkingLevel`, the JSON schema, and no temperature or thinking budget.
- AC4: Every alert candidate records every Part 1 rule check in `checks_json`, with GSTIN, invoice and statement marked `not_applicable` (Q3). A failed check triggers one re-extract with the failures attached. A second failure escalates to high thinking, and a third leaves the candidate `AWAITING_OWNER` with a `confirm_record` question.
- AC5: A duplicate alert (same dedup_key), or one from an unknown sender or account, never reaches the ledger.
- AC6: An irrelevant email stops after sort (IRRELEVANT). A failure or return email queues `reconcile_failure`.
- AC7: SDK errors map to retryable or permanent as in the contract grid. Offline tests cover 429, 500, 400 and timeout.
- AC8: No test makes a network connection; an autouse guard blocks non-loopback connects. `make smoke-gemini` exists, makes at most 3 live calls, and is not run in this batch.
- AC9: `app.ai.client` is the only module that imports `google.genai`. This is enforced by an import-linter contract, and `app.ai` still never imports ledger, db or web.

### Steps (CHG-004)
- [ ] A1 Tracer redaction fix and test (`tokens` survives; `refresh_token`, `api_key` and `password` are still redacted).
- [ ] A2 `parse_inr` and its tests, including a Hypothesis round-trip with `format_inr`.
- [ ] A3 `ai.client.call` with the FakeBackend: thinking validation, schema parse, usage `or 0`, micro-USD cost, the trace step.
- [ ] A4 `GeminiBackend` offline tests through `httpx.MockTransport`: the request shape, a 200 parse, 429/500/400 and timeout mapping.
- [ ] A5 The no-network guard (`tests/conftest.py`) and the google.genai import contract.
- [ ] A6 `MailSource` and `EmlFolderSource`: list_new filtered by sender and since, released by Clock; fetch; search.
- [ ] A7 `store.py` Fernet store, refusing a blank FERNET_KEY, plus `handle_poll_mail`: dedup on unique keys, sync_state.
- [ ] A8 Alert rule checks: `validate/alert.py`, `dates.py` and `duplicates.py`.
- [ ] A9 `handle_process_document`: sort, extract, validate, the retry ladder and routing.
- [ ] A10 Fixtures, the seed's alert sender, and the end-to-end AC1/AC2 test through the worker.
- [ ] A11 `app/ai/smoke.py` and `make smoke-gemini` (written, not run). Then gate.

---

## CHG-005 — Reconciliation: matching, failures, reversals, drift

### Program design

```
+ app/ledger/reconcile.py     # NEW — match_debit, match_credit, handle_failure, check_drift, open_case (TDD "Reconciliation and drift")
~ app/ledger/writer.py        # MODIFIED — record_reported_balance, set_drift_status, confirm_balance (all bank_account changes stay in the writer, D10)
~ app/domain/states.py        # MODIFIED — DRIFT_TRANSITIONS; bank_txn UNMATCHED→REVERSED (reconciler) per PO leaning (Q7)
~ app/jobs/ (handlers)        # reconcile_txn, reconcile_failure, drift_check registered with the worker
~ app/ingest/pipeline.py      # MODIFIED — a reported balance on an alert queues drift_check
+ tests/test_reconcile_match.py  test_reconcile_failure.py  test_drift.py  test_phase4_exit.py
~ tests/test_states.py  tests/test_ledger_transitions.py (new rows)
```

**Matching a debit** (TDD, "A new debit", steps 1–5; the window comes from `matching.window_days`):

```
cands = PAYMENT_EXPECTED payables of the business, amount == debit amount, |planned_date − txn_date| ≤ window
named = [c for c in cands if name_matches(txn.counterparty, party.name or alias)]
normalise: upper, punctuation → space, drop {PVT, PRIVATE, LTD, LIMITED, M/S, MS}, collapse spaces;
           match = counterparty == name or counterparty contains name
len(named) == 1  → atomic: txn UNMATCHED→MATCHED (party_id) + bill →PAID (matched_txn_id) ; enqueue_replan
cands, otherwise → every bill in (named or cands) →REVIEW ; open ambiguous_match case     (Q7)
no cands         → txn stays UNMATCHED ; open unknown_txn case
```

- **Credits** run the same steps against open receivables (COMMITTED, EXPECTED or UNKNOWN), using the `expected_date` window.
  - One match → the receivable becomes CONFIRMED (matched_txn_id) and the txn MATCHED. Then a replan.
  - A name match with a different amount → an `ambiguous_match` case (TDD: "a different amount opens a case").
- **Aliases** are never learned here. The TDD reserves alias learning for owner confirmation.

**Failures and reversals** (TDD, "Failures and reversals"):

```
cands = PAID bills whose matched debit has the same amount and reference == notice.original_reference
      ∪ PAYMENT_EXPECTED bills with the same amount, planned_date within the window of failure_date
exactly one → atomic: bill →REOPENED ; its matched debit MATCHED→REVERSED (if any) ; enqueue_replan
else        → failed_payment case
```

A failure whose debit arrived but was never matched, for example a bill in REVIEW, uses the new row UNMATCHED→REVERSED (reconciler). That is the PO's leaning (Q7), and it is cited from "any original debit is marked REVERSED".

**Drift check** (TDD, "Drift check", steps 1–6; Part 1, "Balance drift"):

```
check_drift(account, reported_paise, reported_at, source):
  writer.record_reported_balance(...)                                   # bank_account change → writer (D10)
  calculated = opening + Σ non-REVERSED txns with opening_at ≤ txn_date ≤ reported_at's date
  equal            → last_reconciled_at = reported_at; if CHECKING/ASK_OWNER only via the rules below
  differs, alert   → enqueue drift_check(recheck=True) run_after = that day 23:00 IST   (step 3, Q11)
  differs, statement or recheck still differs → writer.set_drift_status(OK→CHECKING, 'reconciler') + drift case   (step 4)
new txn written while CHECKING → re-run check against the stored reported balance; gap closed → CHECKING→OK   (step 5, code side)
writer.confirm_balance(account, real_paise, owner, expected_version?) → ADJUSTMENT txn for the difference + ASK_OWNER→OK   (step 6; route in CHG-006)
```

**DRIFT_TRANSITIONS** on `bank_account.drift_status`:

| From | To | Actor | Cite |
|---|---|---|---|
| OK | CHECKING | reconciler | Drift check step 4 |
| CHECKING | OK | reconciler | step 5: findings close the gap |
| CHECKING | ASK_OWNER | reconciler | step 5: otherwise ASK_OWNER (applied by code once the agent, CHG-008, gives up) |
| ASK_OWNER | OK | owner | step 6, via `confirm_balance` only |

Events are `BANK_ACCOUNT_<STATE>` and `BANK_ACCOUNT_REPORTED_BALANCE`. Agent actors are refused.

**Cases.** `open_case` inserts `agent_case` with:
- `kind`;
- `subject_ref` (`bank_txn:<id>`, `payable:<id>`, `bank_account:<id>`);
- `stake_paise` (the amount, or the gap);
- `thinking` = high if the stake exceeds `business.escalation_stake_paise`, else medium;
- a five-part `case_file_md` holding the code-filled facts;
- status OPEN.

It then queues `run_case`. That job stays queued until CHG-008 registers a handler (Q10).

### Contracts consumed (from CHG-004's extract, via `bank_txn` and `candidate`)

| Input | 1. Units | 2. Empty | 3. Absent | 4. Failure | Cite |
|---|---|---|---|---|---|
| `bank_txn.amount_paise` | int paise > 0 (CHECK) | — | NOT NULL | — | code (schema) |
| `bank_txn.counterparty` | free text from the alert | `""` → no name match → REVIEW or unknown_txn by count | NULL → same as empty | — | code (CHG-004 extract, nullable) |
| `bank_txn.reference` | bank ref string | `""` → treated as absent | NULL → failure matching falls back to amount-plus-window on PAYMENT_EXPECTED only | — | code |
| `payable.planned_date` (PAYMENT_EXPECTED) | ISO date | — | NULL → excluded from date-window matching, never matched (writer requires it for PLANNED) | — | code (writer TRANSITION_FIELDS) |
| `party.aliases_json` | JSON array of strings | `[]` → name only | NULL impossible (NOT NULL DEFAULT '[]') | malformed JSON → treated as `[]`, with a trace note | code (schema) |
| reported balance | int paise from `parse_inr` | 0 → a real zero | None → no drift check | — | code (CHG-004) |

### Acceptance criteria (CHG-005)
- AC1: An approved payment plus a matching debit alert moves the bill to PAID and the debit to MATCHED, atomically, and queues a replan.
- AC2: A return or failure email moves the bill to REOPENED and its original debit to REVERSED, then queues a replan. A failure that matches no bill opens a `failed_payment` case.
- AC3: An ambiguous debit (no name match, or several candidates) moves the bill or bills to REVIEW and opens an `ambiguous_match` case. A debit matching nothing stays UNMATCHED with an `unknown_txn` case. Cases start at high thinking when the stake exceeds the escalation amount.
- AC4: A credit matching an open receivable marks it CONFIRMED. A name match with a different amount opens a case.
- AC5: Drift:
  - An alert's available balance that disagrees is rechecked at 23:00. A mismatch that remains sets the account to CHECKING and opens a drift case. A statement mismatch is acted on at once.
  - A later transaction that closes the gap returns the account to OK.
  - `confirm_balance` writes an ADJUSTMENT txn with the owner as actor and returns the account to OK.
- AC6: While drift is unresolved, every planner snapshot uses the lower of the two balances. This is shown through the persisted replan, not only through the planner.
- AC7: Every bank_account and ledger change in this change goes through the writer. The guard (R008) is green, and agent actors are refused for the drift moves.
- AC8: The Phase 4 exit test runs all three scenarios end to end through the worker on the seeded DB with the fake AI. It also shows the debit's trace.

### Steps (CHG-005)
- [ ] R1 `DRIFT_TRANSITIONS`, the bank_txn UNMATCHED→REVERSED row, and the writer functions `record_reported_balance`, `set_drift_status` and `confirm_balance`, with tests.
- [ ] R2 Name normalisation and `match_debit` (match, review, unknown), with tests.
- [ ] R3 `match_credit`.
- [ ] R4 `handle_failure` (PAID, PAYMENT_EXPECTED and never-matched debits) and `failed_payment` cases.
- [ ] R5 `open_case`: thinking by stake and the case file.
- [ ] R6 `check_drift`: the alert recheck at 23:00 with the FakeClock advanced, statements acted on at once, gap closing, `confirm_balance`.
- [ ] R7 Register handlers with the worker. The pipeline queues `drift_check` for a reported balance.
- [ ] R8 `tests/test_phase4_exit.py`: debit → PAID; return email → REOPENED and replan; missing alert → CHECKING. Each runs through the real worker loop. Then gate.

---

## Fixture sources
- **The worked example (seed and golden).** TDD Part 1, unchanged.
- **Test inbox `.eml` files.** Their format follows HDFC Bank InstaAlert debit and credit emails, and a NEFT/UPI return notice: subject line style, "Dear Customer, Rs.X has been debited from account **4821 …", reference number and available balance. Every value is fictional: the sender `alerts@hdfcbank.example` (an `.example` domain, so it can't be mistaken for a real bank sender), account XXXX4821, the amounts and parties from the worked example, and the references. Each file starts with the header `X-Fixture-Note: fictional data; format modelled on HDFC InstaAlerts`. The files are:
  1. A ₹1,80,000 debit to Ashirwad Paper on 12 Oct.
  2. A ₹33,000 credit from Kaveri on 13 Oct.
  3. A return notice for the paper payment.
  4. A debit alert with an available balance that doesn't reconcile, for the missing-alert scenario.
  5. An irrelevant newsletter.
- **Fake AI responses.** These are canned JSON per fixture, written to match each `.eml` by hand. They are labelled as fakes in `tests/fake_ai.py`. The only thing that proves the prompts work against Gemini itself is the live smoke run, when the PO authorises it.

## Questions for PO (each has a default that I'll use if the plan is approved as written)

| # | Question | Recommendation |
|---|---|---|
| Q1 | Where does the worker heartbeat live? There's no table for it, and the TDD says to add none. | A file, `DATA_DIR/worker.heartbeat`, which `/api/health` reads. |
| Q2 | Trace `cost` units. The invariant forbids floats for money, and this cost is USD rather than ledger money. | Integer micro-USD (`cost_micro_usd`), with the rates in `config.yaml`. |
| Q3 | CHG-004 AC4 says "every rule check". GSTIN, invoice and statement checks belong to Phase 6. | For alerts, record all of them, with those three as `not_applicable`. The validators land in CHG-007. |
| Q4 | Should Gemini return amounts as numbers? | No. It returns the amount text verbatim, and code parses it to paise (`parse_inr`), so the model never produces a stored number. |
| Q5 | How should a replan move a PLANNED bill's pay date? There's no PLANNED→PLANNED row. | New `writer.set_planned_date`: planner only, PLANNED only, with a version bump and a `PAYABLE_REPLANNED` event. |
| Q6 | What does ESCALATE mean for state? | The same as WAIT: a PLANNED bill goes back to CONFIRMED. |
| Q7 | Reconciliation ambiguities. | Several candidate bills all go to REVIEW, in one case. Credits use the `expected_date` window. Failures match a PAID bill by amount plus its debit's reference, or a PAYMENT_EXPECTED bill by amount plus the window. Add the UNMATCHED→REVERSED (reconciler) row now. The other leaned rows (owner MATCHED and EXPLAINED, receivable re-rating) land with their callers in CHG-006 and CHG-008. |
| Q8 | `app/ingest/store.py` isn't in the TDD layout. | Add it for Fernet document storage. `poll_mail` refuses to run with a blank FERNET_KEY, and tests generate a key. |
| Q9 | `explain_plan` and `send_alert` have no handlers yet. | Don't queue them in batch 2. New draft CHG-018 for `explain_plan` (diff → Gemini summary, number check, template fallback). `send_alert` stays with SMTP in CHG-009. |
| Q10 | What happens to `run_case` jobs before CHG-008? | They stay queued. The worker claims only kinds that have handlers. |
| Q11 | How is the 23:00 alert recheck scheduled? | A delayed `drift_check` job with `run_after` at that day's 23:00 IST. |
| Q12 | Fixture sender domain. | `alerts@hdfcbank.example`, fictional, set in the seed's `alert_senders_json`. |
| — | Latent bug, flagged: the tracer currently redacts any field whose name contains "token", so the TDD's `tokens` trace field is always blanked. | Fixed in CHG-004 A1. Only fields named or ending in password, token or key are redacted. |
