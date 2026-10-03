# Batch 7: plan (CHG-010b owner alerts; CHG-010a evals and the harness ablation; CHG-010c the evidence docs)

**Goal:** the system shows its own evidence. Every TDD scenario runs repeatedly through a real eval runner, which scores the end result, the path taken and the component that broke. The harness ablation measures what each control is worth on the same model. The owner gets fixed-template email alerts that the AI cannot reach. The README, architecture, threat model, permission model, curated traces and demo script let someone who didn't build it run it and judge it. This is TDD Phase 9 plus the non-Gmail half of Phase 8, and the last build batch before the Gmail handover.

**Branch:** `batch-7`, cut from main at 886da0b. The order is CHG-010b, then CHG-010a, then CHG-010c (Q1).

**Backlog:** CHG-010 (Evidence) splits into CHG-010a (evals and ablation), CHG-010b (owner alerts) and CHG-010c (evidence docs). CHG-009 keeps only the Gmail half (OAuth, GmailSource), which is yours to own; its SMTP part moves to CHG-010b.

**Router:**
- **CHG-010b → `planned`.** It consumes the SMTP contract (stdlib `smtplib`; the server can't be run here, so tests use an in-process fake). Four steps.
- **CHG-010a → `sliced`.** It consumes the Gemini contract in live mode, which can't be run in the build, and the trace format as the source of its trajectory metrics. Seven slices.
- **CHG-010c → `planned`.** Documents generated from, and checked against, the code: the permission table, traces from fixture runs, attack outcomes from tests. Four steps.

**Standing policies:**
- No live Gemini and no live SMTP in the build. Fixture mode only; you authorise the live eval runs after accept.
- Never read .env.
- Gate of record: `make test` through yt_gate.py.
- Review split by subsystem; re-review only the fix commits.
- Push main only after your accept.

---

## CHG-010b: owner alerts by email (planned)

**Your requirements and where each lands:**

| Requirement | Where | Shown by |
|---|---|---|
| `notify/smtp.py` plus a `send_alert` job | `app/notify/smtp.py`, `app/notify/templates.py`, `app/jobs/alerts.py` | Job tests through the worker |
| Fixed templates | `templates.py`: one template per alert kind, and code fills only figures it reads from the database | A test: a party name with markup or newlines gets no header injection, and the body is plain text |
| Recipient from the database only | The business's owner `app_user.email`. The payload carries only a kind and a record reference | A payload with a `to` key is refused (PermanentJobError) |
| `alerts.min_minutes_between_emails` throttle | Unsent alerts collect in a new `owner_alert` table (migration 0005). At most one email per business per window; one inside the window is deferred to the window's end and sent as one digest | Clock tests: three alerts in 10 minutes give one email with three lines |
| A separate SMTP account via env | `SMTP_HOST/PORT/USER/PASSWORD/ALERT_FROM` (already in Settings), plus a new `APP_BASE_URL` for the link | No SMTP host configured: alerts stay unsent, the job logs it, nothing fails |
| Tests use an in-process fake SMTP, no new dependency | `send_email(msg, settings, smtp_factory=smtplib.SMTP)`; tests pass a fake class that records messages | |
| The AI can't reach it | Import-linter: `app.ai` and `app.agent` never import `app.notify` (and agent never imports app.jobs, already true) | Contract kept |

**Steps:**
1. Migration 0005 `owner_alert` (id, business_id, kind, ref, created_at, sent_at). `app/notify/templates.py` holds the TDD's four alert texts (money received, payment failed, unexpected debit, balance mismatch) plus "N items need you", each with a link to `/attention` or `/`. `app/notify/smtp.py` holds `send_email`.
2. The `send_alert` job: read unsent alerts, apply the throttle, build one plain-text email (subject and body from the templates), send it, then mark the alerts sent. An SMTP failure is retried by the queue; with no SMTP configured, nothing is sent.
3. Queue points, all in code (Q7):
   - `money_received`: a credit matched (reconcile result);
   - `payment_failed`: a bill REOPENED;
   - `unexpected_debit`: an unknown_txn or ambiguous_match case opened;
   - `balance_mismatch`: `confirm_balance` asked (in `to_owner`).

   Each writes an `owner_alert` row and queues `send_alert` (one queued job per business absorbs the rest).
4. Tests, the import contract, and `.env.example` gains `APP_BASE_URL` (the documented variable only; I don't read `.env`).

---

## CHG-010a: the eval system and the harness ablation (sliced)

**Your requirements and where each lands:**

| Requirement | Slice | Shown by |
|---|---|---|
| `evals/runner.py`, `evals/report.py`, `evals/ablation.py`; `make evals` and `make ablation` replace the stubs | S1, S5, S6 | Make targets run; with no args they print usage and exit non-zero |
| All 11 TDD scenarios in `evals/scenarios/<name>/` (emails, uploads, `expected.yaml`), reusing the fixtures with no duplicated replies | S2, S3 | A test: the 11 names match the TDD table, every scenario passes in fixture mode, and no scenario folder holds a reply |
| Three levels: end-to-end, trajectory (tool calls, loops, wasted calls, retries, escalations, from the traces), component (sort, extract, validate, reconcile, planner or agent) | S1, S4 | Report columns. Each expectation is tagged with its component, and the first failed one, in pipeline order, names the broken component |
| N=5 runs per scenario; success rate, spread and worst case, plus tokens and cost per scenario | S4 | Report rows |
| `--ai fixtures` is offline and deterministic, and runs in `make test` as a fast check; `--ai live` uses real Gemini | S1, S7 | A pytest test runs the suite at N=1 in fixture mode |
| A HARD budget guard in code for live mode: at most 600 calls and 5,000,000 micro-USD per invocation; a clean abort with a partial report; sequential runs with a small delay; a 429 backs off and resumes | S5 | `BudgetGuard` wraps the backend and is tested with a fake backend: call 601 aborts; a cost overrun aborts; a 429 sleeps (injected sleeper) and resumes; the partial report is written and marked ABORTED |
| Harness ablation per the TDD: same model; bare = all tools, no rule checks, no escalation, no case file, the model computes balances and the plan; scored against golden. Then full vs bare, and knock-outs: no planner, no rule checks, no escalation, no drift rule | S6 | The ablation report table: one row per harness, plus a "which component earned the most" line |
| One regression caught, honestly: a degraded variant; show the drop; keep both reports | S7 | `docs/evals/` holds the baseline report and the regression report, from fixture mode, now |
| Don't run live in the build. Reports go to `docs/evals/` with model, prompt version, commit and date | all | Report header |

**Slices:**

**S1. The runner core.**
- `evals/runner.py` builds a fresh migrated and seeded database per run in a temp dir, with its own `FakeClock`, settings and trace dir.
- It executes a scenario's steps, drains the real worker (`default_handlers(backend)`), and evaluates the expectations.
- Step vocabulary:
  - clock: `at`;
  - mail: `deliver` (from fixtures/test_inbox, agent_inbox or the scenario folder), `poll`;
  - uploads: `upload` (through `actions`, as the web app does);
  - plans: `monday_plan`, `approve` (the owner's approval of the next payment day, through `actions`), `choose_option`;
  - the owner's answers: `confirm_waiting`, `unlock` (password typed as the owner would), `answer`;
  - `drain`.
- Expectation kinds: `sql` (equals or rows), `plan` (lowest, on, decision per bill), `alert` (an `owner_alert` kind exists), `question` (an open question of a kind). Each one is tagged with a component.
- CLI: `python -m evals.runner --ai fixtures|live --runs N [--scenario name] [--config variant.yaml] [--label x]`.

**S2. Scenarios 1–6, the pipeline ones:**
1. debit alert for a planned payment;
2. password-protected statement;
3. handwritten bill photo;
4. Hinglish voice note "dedh lakh";
5. same invoice by email and photo;
6. payment returned. "Owner told" is an `owner_alert` of kind `payment_failed`, which is why CHG-010b comes first.

**S3. Scenarios 7–11, the agent and planner ones:**
7. missed alert causes drift (fixture 11);
8. drift with no explanation;
9. vendor email changes bank details (fixture 09);
10. hidden instruction in a vendor email (09 plus the hidden-urgent email; Q6);
11. shortfall week (the worked example: ₹1,83,000 and the three options as golden).

**S4. Trajectory and component metrics; the report.**
- `evals/metrics.py` reads each run's trace files and job table:
  - AI calls, and agent tool calls by tool;
  - refused calls (unknown tool, bad args, repeats: loops);
  - schema failures;
  - INVALID candidates;
  - job retries (attempts > 1);
  - escalations (escalation steps with a rule);
  - tokens in, out and thought, and cost in micro-USD.
- "Wasted calls" = refused calls plus schema-failed replies plus INVALID candidates.
- `evals/report.py` writes `report.md` and `report.json` into `docs/evals/<date>-<mode>-<label>/`. The header holds model, prompt version, config hash, commit, date, mode and N. Per scenario it gives:
  - the success rate (k of N);
  - the spread (the min and max share of expectations met);
  - the worst run (its failed expectations and the component);
  - the mean trajectory metrics;
  - tokens and cost (mean and max).

  A run that hit an infrastructure error (a 429 that exhausted its backoff, the budget abort) is ERRORED, not FAILED, and is counted separately (Q8).

**S5. Live mode and the budget guard.**
- `BudgetGuard(backend, max_calls=600, max_micro_usd=5_000_000, delay_s=1.0, sleep=time.sleep)` counts every call and adds the cost from the response's usage at the config's pricing.
- Before a call that would exceed either cap, it raises `BudgetExceeded`. The runner catches it, stops, and writes the partial report marked ABORTED with what ran.
- On a 429 it sleeps 5, 10, 20, 40 and then 60 seconds and retries the call itself; after that it surfaces the error as ERRORED.
- Runs are sequential.
- `--ai live` builds `GeminiBackend` from Settings, needs `--yes-spend` and prints the caps first.

**S6. The harness ablation** (`evals/ablation.py`, `make ablation`).
- **bare:** a naive loop in `evals/bare.py`.
  - One growing chat history, and every tool exposed, write tools included: read mail, read the ledger, record a transaction, set a bill's status, set a priority, write the plan.
  - It runs against a scratch copy of the database, with no rule checks, no case file, no escalation and no step limit beyond a hard cap of 20.
  - At the end the model outputs the balances and plan as JSON. Code scores them (and the database state) against the same scenario's golden expectations.
- **Knock-outs on the full harness**, each patched at a named seam at runtime by `evals/knockouts.py`, never as flags in app code (Q3):
  - `no_planner`: the plan comes from the model, as in bare;
  - `no_rule_checks`: every app/validate check returns passed;
  - `no_escalation`: no stake rule, no rerun at high, a 20-step cap;
  - `no_drift_rule`: the planner uses the calculated balance even when the account isn't OK.
- The report shows the full, bare and each knock-out success rate on the same scenarios and N. "Which component earned the most" is the knock-out with the largest drop.
- In fixture mode, bare and no_planner need model replies that aren't scripted. They run on short scripted replies to prove the mechanics, and the report labels those rows "mechanics only, needs live". The real numbers come from your live run.

**S7. One regression caught; the fast check.**
- `evals/variants/` holds config overlays merged over config.yaml (TDD change control: model and prompts settings in config).
- The offline regression is `regress-max-steps.yaml`, with `escalation.max_steps: 2`, a "save cost" change someone might make. The drift-recovered scenario then can't finish in 2+2 steps and ends at the owner, and the suite catches the drop (Q5).
- The baseline and regression reports are both committed under `docs/evals/`.
- `prompt-degraded.yaml` (prompts version `…-regress`, with an extract prompt that drops the available balance) is prepared for your live run. Fixture replies ignore prompts, so it can't show anything offline, and the report says so.
- `tests/test_evals.py` holds the fast check: the 11 scenarios pass at N=1 in fixture mode, the budget guard tests, the knock-out seams, and the report schema.

---

## CHG-010c: the evidence documents (planned)

1. **`README.md`:**
   - what it is;
   - an architecture summary;
   - a quickstart: `make setup`, `make db`, `make reseed`, `make run`, `make worker`; demo mode with `DEMO_NOW` and `DEMO_AI=fixtures`; the demo logins; live-AI notes;
   - the walkthrough script;
   - known limits, including CHG-026's crash on a run's last attempt, the silent voice fixture, and the italic "handwritten" photo;
   - the eval and ablation commands, with links to the reports;
   - the flagged reusable component: `app/validate`, the Indian finance validators (GSTIN check digit, invoice arithmetic, statement arithmetic, spoken amounts), with a usage example that a test executes;
   - a Gmail section as a placeholder that says the user owns it.
2. **`docs/architecture.md`:** a Mermaid diagram labelling:
   - the agent loop and the five tools;
   - context management (the case file, the 20-line cut, the trace holding the full result);
   - the control points: the writer's refusal of `agent:*`, the rule checks, escalation, the stale-plan refusal, the import contracts, the evidence check in apply_final, and code applying every answer.
3. **The threat and permission documents:**
   - **`docs/threat-model.md`** (one page): the lethal-trifecta analysis, the threat table, and the documented attack (the TDD's two planted emails), with the actual outcome. That outcome is quoted from `test_ac4` and its trace, plus the known limits.
   - **`docs/permission-model.md`:** the generated tool table (the same generator as agent-permissions, checked by a test) and the roles table (the route-table test is the source).
4. **`docs/traces/` and the demo script:**
   - `success.jsonl` and `failure.jsonl`, generated by a script from fixture runs, each with a "how to read this trace" walkthrough:
     - success: the drift recovered from mail;
     - failure: the same scenario under the max-steps regression, where the agent hits its limits and the case reaches the owner, read from the escalation_rule (Q10).
   - `scripts/make_traces.py` regenerates them, from a live run later.
   - `docs/demo-script.md`: a 3-minute script for you to record. Nothing is recorded.

**Minors folded in (same paths only):** CHG-026's crash edge case goes into the threat model and README known limits, as you asked. No CHG-025 item touches these paths.

---

## Contracts consumed (enumeration)

| Contract | Values this batch relies on | Unknown |
|---|---|---|
| Trace JSONL (ours) | `tool` (`ai.call:<job>`, `agent:<tool>`, `escalation`, `apply_final`, `check_summary`), `escalation_rule`, `validation`, `tokens{input,output,thoughts}`, `cost_micro_usd`, `result` | none (we wrote it; S4 adds a test pinning the fields it reads) |
| Gemini usage → cost | `RawAIResponse` token counts × `config.model.pricing` (micro-USD per Mtok; output includes thoughts) | The real per-call cost is only known live, so the guard also checks the smoke's 3,214 micro-USD for 3 calls as a sanity anchor |
| HTTP 429 | `AIUnavailable(retryable=True, code=429)` from GeminiBackend | Retry-After headers aren't read (the SDK doesn't surface them); fixed backoff instead |
| SMTP (stdlib) | `smtplib.SMTP(host, port)`, `starttls()`, `login()`, `send_message()`; any `smtplib.SMTPException` or `OSError` is retried by the queue | TLS mode: STARTTLS on 587 only (Q7) |

## Open questions (defaults in place; say a word to change any)

- **Q1:** three changes, not two. Notify is separate from the docs because the evals' "owner told" check needs it first, and the docs cite eval reports and traces made last. Order: 010b, 010a, 010c.
- **Q2:** in scenario 6, "owner told" means an `owner_alert` row of kind `payment_failed`, not a sent email (SMTP is fake in evals).
- **Q3:** ablation knock-outs patch named seams at runtime from `evals/knockouts.py`, never as eval flags in app code. Each seam is listed in the report.
- **Q4:** bare and no_planner give mechanics-only numbers offline (scripted replies) and are labelled so. The ablation numbers that count come from your live run.
- **Q5:** the offline regression is the `escalation.max_steps: 2` config variant. The degraded-prompt variant is prepared but only shows a drop live.
- **Q6:** the hidden-instruction email becomes a fixture, `fixtures/agent_inbox/12-hidden-urgent.eml`, with its fixture-AI replies in ai_replies.json under the existing store (a new `agent_inbox` folder key). FixtureBackend reads texts from agent_inbox too. test_ac4 reuses it instead of building it inline.
- **Q7:** alert queue points are the TDD's four events, and email is a digest per throttle window. TLS is STARTTLS on port 587 only. The link base is `APP_BASE_URL`, default `http://localhost:8000`.
- **Q8:** ERRORED (infrastructure: a 429 that exhausted its backoff, a budget abort) is reported apart from FAILED (the system got it wrong) and doesn't count against the success rate's denominator. The report shows both.
- **Q9 (live budget, yours to set at run time):** the full suite at N=5 is about 55 runs and roughly 300–600 calls, so the full suite and the ablation are separate invocations, each under its own 600-call / $5 cap. The guard enforces it either way.
- **Q10:** the failure trace is the drift scenario under the max-steps regression (a real failure, handled by escalation to the owner), not a synthetic error.

**Risks:**
- The live voice scenario uses a silent WAV (its canned reply is the transcript), so live it will fail on audio. A real Hinglish clip is needed; it's in known limits until you supply one.
- The "handwritten" photo is an italic rendering. A live photo test is weaker evidence than real handwriting; also in known limits.
- The bare harness on real Gemini may take write actions against its scratch database by design. It never touches the real database (it uses a temp copy).
- Live costs are bounded by the guard. The estimate is $1–3 per full-suite invocation at N=5.

## PO decisions (2026-10-03; plan 138f737 approved by payablesagent-ac)
- **Scope:** three changes, in the order CHG-010b, CHG-010a, CHG-010c. Q1–Q10 defaults are accepted.
- **D22 (the voice fixture):** make it real with no new dependency. A committed generator script uses Windows' built-in speech synthesiser (System.Speech) to speak "Sharma Packaging ka bill, dedh lakh rupaye, paanch November tak dena hai." Commit the WAV with its source noted. If the installed voice can't produce something intelligible, keep the silent fixture, list it as a known limit, and add a handover line asking the user for a 5-second recording. Fixture mode is unaffected either way.
- **D23 (the regression story):** max_steps: 2 is the offline-provable regression. The degraded-prompt variant stays ready for live. The PO runs both live, and the report shows whichever the live suite actually catches.
- **D24 (fair bare scoring):** the bare model gets the same inputs (the emails and the seeded state, as text), the same model and the same thinking level. Only the harness differs, and the ablation report header says so.
- **D25 (no hand-typed figures):** every docs page that quotes a number (a cost, a success rate, a test count) says which run or commit it came from.
- **After accept:** the PO authorises the live evals and the ablation, each under the $5 cap.
