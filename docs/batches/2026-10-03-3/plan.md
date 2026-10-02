# Batch 3 — Plan

**Covers:** CHG-020 (the AI error message, lane `direct`) and CHG-006 (the owner web app, TDD Phase 5, lane `sliced`).

**Branch:** `batch-3`, cut from `main` at the commit that records this plan's approval.

**Order:** CHG-020 first. Then CHG-006 in six vertical slices, S1 to S6, each ending in a green gate. They run in sequence because every slice builds on S1's auth layer.

**Exit (TDD Phase 5):** the owner plays through the worked example in the app. The gate of record is an httpx `TestClient` test that drives the walkthrough through the real routes on the seeded database. The PO walks it through in a browser at verdict time. No Playwright and no new dependency.

**Router:**
- **CHG-020 → `direct`** (set by the PO). One module, and the result shows in one test.
- **CHG-006 → `sliced`.** Two triggers move it up:
  - The finished result can't be shown with one command or on one screen: five screens and about twenty routes.
  - It is cross-module work: auth, the ledger writer, planner reads, the job queue, and templates.

  It also consumes small library contracts it didn't write (itsdangerous, argon2-cffi, python-multipart, Starlette's TestClient cookies), so the plan enumerates them below.

**Standing policies (PO):**
- No live Gemini call. The web process never imports `app.ai`, and a new import-linter contract enforces that.
- Never read or print `.env`. Demo passwords come from environment variables, with dev defaults documented in `.env.example`.
- No Gmail or OAuth code. On `/accounts`, the Gmail row reads "Not connected (set up later)".
- Local `make test` through `yt_gate.py` is the gate of record.

**Dependencies:** no Python dependency is added. `jinja2`, `python-multipart`, `itsdangerous` and `argon2-cffi` are already pinned.

HTMX and Pico.css are vendored as static files into `app/web/static/`, as the TDD requires, so the app runs without a CDN. That means one download each from jsdelivr, with the version, source URL and sha256 recorded in `app/web/static/VENDORED.md` (Q11). They are not Python packages, so R002 doesn't apply, but I'm flagging the download for approval.

---

## CHG-020: the SDK's error message, redacted (direct)

- `AIUnavailable` gains `detail`: the SDK's own message (`APIError.message`, or the httpx exception text).
- That detail is redacted twice before it goes anywhere:
  - any substring that looks like a Google API key (`AIza[0-9A-Za-z_-]{30,}`) is replaced;
  - so is the literal key the backend was built with.

  The redacted detail then reaches `str(e)` (so `job.last_error`) and the trace step's validation text.
- **The test:** a MockTransport 403 whose message echoes the key, and a second variant with only an AIza-shaped string. Neither the key nor the AIza string appears in the exception, in the last_error of a job that raised it, or in the trace file.
- The mapping is unchanged: 403 and other 4xx except 429 are permanent; 429, 5xx, a code of None and transport errors are retryable. The existing tests stay as they are.
- Expected paths: `app/ai/client.py`, `tests/test_ai_client.py`, and `tests/test_pipeline.py` for the last_error check.

## CHG-006: owner web app (sliced)

### Program design

```
+ app/web/__init__.py
+ app/web/app.py            # mounts routes, static files, templates (autoescape on); main.create_app() includes it
+ app/web/auth.py           # argon2 verify, itsdangerous session, CSRF, current_user and require_role dependencies
+ app/web/repo.py           # the one read layer the web uses; every query filters on the user's business_id
+ app/web/actions.py        # owner actions: writer calls plus the inline replan, one transaction each
+ app/web/routes/{auth,week,attention,add,accounts,settings,api}.py
+ app/web/templates/*.html  # base, login, week, attention, add, accounts, settings, plus fragments for HTMX swaps
+ app/web/static/htmx.min.js  pico.min.css  VENDORED.md
~ app/main.py               # create_app() includes the web app; /api/health unchanged
~ app/config.py             # session_secret required by the web app; cookie_secure; seed_owner_password, seed_helper_password
~ app/ledger/writer.py      # update_business_settings(), set_priority(); see Q7
~ app/domain/states.py      # bank_txn UNMATCHED creatable by the owner, for confirming an alert candidate (Q6)
~ fixtures/seed.py          # real argon2 demo login (owner 1, helper 2); passwords from Settings
+ fixtures/test_inbox/07-credit-nandi-foods.eml   # ₹2,00,000 credit, Fri 16 Oct (fictional), for the exit walkthrough
~ tests/fake_ai.py          # canned replies for 07
~ .env.example              # SESSION_SECRET note, SEED_OWNER_PASSWORD, SEED_HELPER_PASSWORD with dev defaults
~ pyproject.toml            # import-linter: web never imports ai
~ CLAUDE.md                 # make run now serves the app; demo login
+ tests/web_helpers.py  test_web_auth.py  test_web_roles.py  test_web_week.py  test_web_attention.py
+ tests/test_web_add.py  test_web_accounts_settings.py  test_web_api.py  test_web_plain_text.py  test_phase5_exit.py
```

**Auth (S1):**
- **Login:** POST `/login` with email and password, checked with `argon2.PasswordHasher().verify`. A failed login gets the same message whether the email or the password was wrong. On success, the user gets a signed session cookie: `URLSafeTimedSerializer(SESSION_SECRET)` holding the user id and a CSRF token.
- **Cookie:** HttpOnly, SameSite=Lax, path `/`, max age 12 hours. Secure is set only when `COOKIE_SECURE` is true (Q10).
- **SESSION_SECRET:** if it's blank, the web app refuses to start. The message names the one-line command that makes a secret, the same pattern as FERNET_KEY.
- **CSRF:** every POST must carry `csrf_token`, either as a form field or as the `X-CSRF-Token` header that HTMX sends through `hx-headers` on `<body>`. It is compared with the session's token in constant time; a missing or wrong token gets 403. The login form uses a pre-session CSRF cookie. Logout is a POST.
- **Roles:**
  - `current_user` loads the `app_user` row from the session. With no valid session, a page request redirects to `/login` and an action gets 401.
  - `require_role("owner")` returns 403 for a helper. It is a dependency on every route except `/login`, `/logout`, `/api/health` and the static files.
  - A table-driven test hits every owner-only route as a helper and expects 403. It also checks that the app's route list matches the table exactly, so a route added without a role fails the test.
- **Business isolation:** `repo.py` takes `business_id` from the user on every query. Ids in a path are looked up within that business, and a miss is a 404.

**This week (S2):** GET `/` shows:
- the current plan's days, with each PAY line under its pay day;
- the lowest balance against the safety amount, in Part 1's own figures (₹1,83,000 on Thu 22 Oct, ₹67,000 below);
- WAIT and ESCALATE lines with their reasons;
- one Approve button for the next payment day.

POST `/plans/{run_id}/approve`:
- **Refused as stale (Q3) when any of these holds:**
  - the run isn't the business's current run;
  - the current snapshot's `inputs_sha256` differs from the run's, because the ledger or the date changed since the page was opened;
  - a bill's version in the form differs from its row.
- **Then:** the response is 409 with the current figures re-rendered and the line "The plan changed since you opened it. Here is the current plan."
- **Otherwise:** each PAY line for the next payment day (Q4) moves PLANNED → PAYMENT_EXPECTED. Each move is an owner `transition` that passes `expected_version`. The inline replan follows (Q2).

GET `/api/plan/current` returns the current run as JSON. It is owner-only.

**Needs attention (S3):** GET `/attention` lists:
- open owner questions;
- candidates waiting for confirmation (VALID typed entries, and AWAITING_OWNER alert candidates);
- accounts that aren't OK;
- the current run's shortfall options.

Every field that came from the AI or from a document is rendered as plain text.

POST `/candidates/{id}/confirm` takes a form with the record's fields, prefilled and editable. The edited record goes through the same rule checks again.
- A payable candidate: `create_payable` (owner), then DRAFT → CONFIRMED (owner), then the candidate becomes ACCEPTED, then the inline replan.
- A receivable candidate: `create_receivable` (owner), then the replan.
- A txn candidate: `create_bank_txn` (owner, UNMATCHED; Q6), then `reconcile_txn` is queued.

POST `/candidates/{id}/reject` marks the candidate REJECTED.

**Add (S3):** GET `/add` shows a typed-entry form and a file upload. A helper sees only the source documents and candidates they submitted, with their status. An owner sees everything.
- POST `/entries` turns the typed entry into a `source_document` (kind typed, `submitted_by`) plus a candidate (Q8). Amounts are parsed with `parse_inr`, so "1,20,000" and "Rs.1,20,000" both work.
- POST `/uploads`: the file is stored encrypted (`DocumentStore`) and a `source_document` is created (photo, pdf or voice, from the content type; Q5). Processing waits for CHG-007, so a helper sees "waiting".

**Options and paying (S4):**
- POST `/options/{id}/choose` records `chosen_by` and `chosen_at` on the shortfall_option, then applies the kind (Q1), then the inline replan:
  - **early_receipt:** no ledger change. The owner calls the customer, and the money counts when it arrives (Part 1, "What happens next").
  - **split:** `split_payable` as the owner, with pay-now from the option's params, on the original due date, and the rest due on `rest_due`.
  - **ask_ca:** adds a `ca_reminder` owner question.
  - **authorise_breach and delay_flexible:** the choice is recorded; making the planner honour it is a new draft, CHG-021 (Q1).
- POST `/payables/{id}/mark-paid`: PAYMENT_EXPECTED or REVIEW → PAID, by the owner, with the version from the form. Then the inline replan.
- POST `/api/what-if` runs `plan()` and `options()` on the current snapshot with the changes in the body (Q9) and returns JSON. It writes nothing; a test proves no row changed.

**Accounts and settings (S5):**
- GET `/accounts` shows each account's calculated and reported balance, its drift status and its last reconciled time, and the Gmail row "Not connected (set up later)".
- POST `/accounts/{id}/confirm-balance` calls `writer.confirm_balance`. It applies only to an account in ASK_OWNER, otherwise it returns 409.
- POST `/questions/{id}/answer` handles the question kinds that exist today:
  - `confirm_record` hands off to the candidate's confirm or reject, through its `choices_json` link (CHG-019);
  - `confirm_balance` hands off to confirm-balance.

  Agent questions (`explain_txn` and others) return 409 until CHG-008 (Q5).
- POST `/documents/{id}/unlock` and POST `/parties/{id}/bank-change` are registered, owner-only and CSRF-checked. They return 409 ("nothing to unlock" or "no pending bank change") until CHG-007 creates LOCKED documents and pending bank changes (Q5). The unlock route never sends the password to the tracer or a log, and a test checks this.
- GET and POST `/settings` change safety amount, payment days, horizon, escalation amount and language through `writer.update_business_settings`, which records a BUSINESS_SETTINGS_CHANGED event. They change a bill's priority through `writer.set_priority`, which records a PAYABLE_PRIORITY_CHANGED event. Each change is followed by the inline replan.

**Plain text (all slices):**
- Jinja autoescape is on for every template.
- A test scans the templates and `app/web` for `|safe`, `Markup(`, `autoescape false` and `{% raw`, and fails on any.
- A test plants HTML and script in an extracted counterparty, a candidate field, a plan reason and a case file. It checks that the page shows the characters escaped and that no attribute injection gets through.

### Contracts consumed

| Input | 1. Units / shape | 2. Empty | 3. Absent | 4. Failure | Cite |
|---|---|---|---|---|---|
| `argon2.PasswordHasher().verify(hash, pw)` | True, or raises | empty password → VerifyMismatchError | the seed's old `!` hash → InvalidHashError | VerifyMismatchError and InvalidHashError → the same "wrong email or password" | code: argon2-cffi API, tested |
| `URLSafeTimedSerializer.loads(cookie, max_age)` | dict | `""` → BadSignature | no cookie → not logged in | BadSignature or SignatureExpired → not logged in; cookie cleared | code: itsdangerous, tested with a tampered cookie and an expired one (FakeClock is not used by itsdangerous, so expiry is tested with `max_age` and a monkeypatched time) |
| Form fields (`python-multipart`) | str | `""` → a field error, re-rendered | missing → 422 shown as a field error, not a stack trace | an oversized upload (over 10 MB) → 413 | code: FastAPI Form/UploadFile, tested |
| Amount text in forms | rupees as typed | `""` → field error | missing → field error | `parse_inr` refusal → field error, never a guess | ours (parse_inr) |
| `plan_run.inputs_sha256` vs a fresh snapshot | hex | — | no current run → `/` shows "No plan yet" and offers no approve | a hash mismatch → stale (409) | code (CHG-013) |
| `shortfall_option.params_json` | canonical JSON (int paise, ISO dates) | `{}` (ask_ca) → no params needed | — | malformed → 409 "option can't be applied", nothing written | code (CHG-003/013) |
| `owner_question.choices_json` | `{"candidate_id": N}` for confirm_record | — | NULL → 409 | a candidate outside the business → 404 | code (CHG-004; CHG-019 note) |

### Slices and steps

- [ ] **S1 Auth and shell:**
  - Settings: `session_secret` required by the web app; `cookie_secure`; the two seed passwords.
  - `auth.py`: login, logout, session, CSRF, `current_user` and `require_role`.
  - The base template with HTMX and Pico vendored.
  - The seed creates owner 1 and helper 2 with argon2 hashes.
  - `.env.example`, and the import-linter contract that web never imports ai.
  - Tests: login and logout; tampered and expired cookies; CSRF missing or wrong; the route-table role matrix (every owner-only route returns 403 to a helper; the route list matches the TDD table minus Gmail); helper isolation.
  - Gate.
- [ ] **S2 This week and approve:**
  - `repo.current_plan`, the `/` page, POST approve with the three stale checks and the inline replan, and `/api/plan/current`.
  - Tests: the worked-example figures shown; approve moves only the Mon 12 PAY line; each of the three stale cases is refused with current figures; approve twice is refused.
  - Gate.
- [ ] **S3 Needs attention and Add:**
  - The `/attention` lists, candidate confirm (with edits and checks) and reject, `/add` with the helper's view, `/entries` and `/uploads`.
  - Tests: confirm a typed bill → CONFIRMED and planned; a helper's entry appears only to that helper; uploads are stored encrypted with the source document waiting.
  - Gate.
- [ ] **S4 Options, mark-paid, what-if:**
  - Choose with the per-kind semantics (Q1), mark-paid, and what-if.
  - Tests: split → Prime Chem's ₹53,000 PAY on Thu 22, with lowest ₹2,50,000; early_receipt → recorded with no ledger change; mark-paid on PAYMENT_EXPECTED and on REVIEW, refused from PLANNED; what-if writes nothing.
  - Gate.
- [ ] **S5 Accounts, questions, settings:**
  - `/accounts`, confirm-balance, question answers, the unlock and bank-change refusals, settings, and the two writer functions.
  - Tests: settings events and the replan; priority change; confirm-balance on ASK_OWNER; the unlock password never in the trace.
  - Gate.
- [ ] **S6 Exit walkthrough:**
  - `tests/test_phase5_exit.py` through TestClient on the seeded DB, at Mon 12 Oct 09:00:
    1. The owner logs in.
    2. `/` shows ₹1,83,000 on Thu 22 Oct, ₹67,000 below.
    3. The owner types a bill on `/add`, confirms it on `/attention`, and the plan updates.
    4. The owner approves Monday: Paper becomes PAYMENT_EXPECTED.
    5. The owner chooses "Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct".
    6. The owner marks Paper paid.
    7. Time advances to Fri 16. The worker processes `07-credit-nandi-foods.eml` with the fake AI. Nandi becomes CONFIRMED and the plan reruns.
    8. `/` shows Prime Chem PAY on Thu 22 Oct, with the lowest balance ₹3,83,000, Part 1's "What happens next".
  - A helper login at every step sees only `/add`.
  - Gate.

### Acceptance criteria (CHG-006)

- **AC1:** The owner plays through Part 1's worked example through the app's routes: confirm a bill, approve the plan, choose a shortfall option, mark a payment paid, and see the plan rerun to ₹3,83,000 after Nandi's credit. This is driven by `tests/test_phase5_exit.py` through the real routes and checked in a browser by the PO. The walkthrough's audit trail has an event for every owner action, with actor owner:1 (PO addition).
- **AC2:**
  - Login uses argon2 and a signed session cookie (HttpOnly, SameSite=Lax).
  - Every POST needs a valid CSRF token.
  - The role check runs server-side as a FastAPI dependency on every route.
  - A helper gets 403 on every owner-only route and sees only their own submissions on `/add`.
  - A table-driven test covers every route.
- **AC3:** Approving a plan that isn't current is refused (a run that isn't current, an inputs hash that changed, or a bill version that moved) and shows the current figures.
- **AC4:** AI-authored and document-sourced text renders as plain text everywhere: autoescape is on, there is no `|safe` or `Markup` (enforced by a test), and planted HTML renders escaped.
- **AC5:** The five screens and every route in the TDD's HTTP routes table except the three Gmail routes exist with their roles. Routes whose backend lands later (unlock, bank change, agent answers) refuse with 409 and a plain message. `/accounts` shows Gmail as "Not connected (set up later)".
- **AC6:** Settings changes and priority changes are recorded as events through the ledger writer and followed by a replan. Choosing a shortfall option records the choice and replans; split also performs the split.
- **AC7:** The seed creates a real demo login (owner and helper) from SEED_OWNER_PASSWORD and SEED_HELPER_PASSWORD, with dev defaults documented in `.env.example`. A blank SESSION_SECRET stops the web app with a message naming how to make one.
- **AC8:** The web layer never imports `app.ai`, enforced by import-linter. HTMX and Pico are served from `app/web/static/` with no CDN, and the layout is mobile-first (Pico's responsive container, a single column under 600px).

## Questions for the PO (each has a default I'll use if the plan is approved as written)

| # | Question | Recommendation |
|---|---|---|
| Q1 | What does choosing each shortfall option do? The TDD says only "records the chosen shortfall option and re-plans". | early_receipt: record and replan, with no ledger change; the money counts when it arrives (Part 1, "What happens next"). split: record, then `split_payable` as the owner using the option's figures, then replan. ask_ca: record and add a ca_reminder question. authorise_breach and delay_flexible: record only for now. Making the planner pay an authorised escalated bill, or use a flexible bill's grace days, needs a planner override, which I'd draft as a new change, CHG-021, not in batch 3. |
| Q2 | Should owner actions replan inline or queue a replan job? | Inline, in the same transaction as the action. The page then shows the new plan at once, and the next approval isn't refused as stale while a queued replan waits for the worker. The planner is pure and fast, and it never calls Gemini. |
| Q3 | What makes a plan stale for approval? | Any one of: the run isn't current; the current snapshot's inputs_sha256 differs from the run's (so the date rolling over also makes it stale); a bill's version in the form doesn't match. |
| Q4 | Which lines does "approve" approve? | The PAY lines for the next payment day only, meaning the earliest pay_on among PLANNED PAY lines, as the TDD route says. Later days are approved on their own. |
| Q5 | Routes whose backend arrives later: uploads processing, PDF unlock, vendor bank change, agent-question answers. | All are registered, owner or helper as the table says, and CSRF-checked. /uploads stores the file encrypted and creates the source document, but queues no processing until CHG-007. Unlock and bank-change return 409 until CHG-007 creates something for them to act on. Answers work for confirm_record and confirm_balance questions; agent questions return 409 until CHG-008. |
| Q6 | Confirming an AWAITING_OWNER alert candidate means the owner creates a bank_txn, but CREATE_RULES allows only the pipeline to create an UNMATCHED txn. | Add the owner to bank_txn UNMATCHED creation. This is the TDD's step 5: "ask the owner to fill the fields that still fail". reconcile_txn is queued afterwards. |
| Q7 | The business settings and bill priorities aren't ledger tables, but "every change is recorded as an event", and only the writer writes events. | New writer functions: `update_business_settings` (owner only, BUSINESS_SETTINGS_CHANGED event with before and after) and `set_priority` (owner only, PAYABLE_PRIORITY_CHANGED, version bump). Language is stored, but the UI is English only for now. |
| Q8 | Typed entries. | A typed bill or sales invoice becomes a source_document of kind typed (with submitted_by) and a candidate (created_by `user:<id>`), checked with the same rule checks. It always goes through confirmation, even when the owner typed it, so the path is the same as for extracted bills. |
| Q9 | What does /api/what-if accept? | JSON with optional `receivable_dates` (`{id: "YYYY-MM-DD"}`, counted as COMMITTED), `drop_payables` (`[id]`) and `safety_paise`. It returns plan and options JSON and writes nothing. |
| Q10 | Session details. | itsdangerous signed cookie with a 12-hour max age, HttpOnly and SameSite=Lax. Secure is on only when COOKIE_SECURE=true, because local http can't use it. A blank SESSION_SECRET refuses to start, naming `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| Q11 | Vendoring HTMX and Pico needs one download each. | htmx 2.0.x `htmx.min.js` and Pico 2.x `pico.min.css` from jsdelivr, with versions, URLs, sha256 and licences (both permissive: BSD-2 and MIT) recorded in `app/web/static/VENDORED.md`. |
| Q12 | Demo login defaults. | Owner `owner@example.test` and helper `helper@example.test`. The passwords come from SEED_OWNER_PASSWORD and SEED_HELPER_PASSWORD, with dev defaults `owner-demo-pass` and `helper-demo-pass` documented in `.env.example`. The seed prints the logins it created, never a password from `.env`. |
| Q13 | Part 1's message examples ("Your 14-day plan is ready. Lowest projected balance ₹1.83L ..."). | Pages show figures built by code from the plan. The plain-language change summary is CHG-018 (explain_plan), so batch 3 has no AI-written prose. |
| Q14 | Which CHG-019 items to fold in? | Only the `choices_json` candidate link, which this change reads in /questions/{id}/answer. Candidate "done" states: an owner-confirmed candidate becomes ACCEPTED; I'd leave bank-alert candidates, written by the pipeline, as they are. |
| Q15 | Size. | This is the biggest batch so far, at about 20 routes. If you'd rather split it, the natural cut is S1 to S3 now (auth, This week, Needs attention and Add), with S4 to S6 as batch 4. My default is one batch, because the exit needs all six slices. |

## PO decisions (2026-10-03, plan d2b1e87 approved by payablesagent-ac)
- One batch (Q15). All Q1-Q15 defaults accepted.
- Q1: CHG-021 (planner override for authorise_breach and delay_flexible) is MVP scope and lands in batch 4 with CHG-007. The override is an owner-recorded, evented input to the snapshot; the planner stays pure (the override is data in the snapshot, not a flag the planner reads from elsewhere).
- Q2: the inline replan calls the same function the replan job uses (`app.jobs.replan.replan`), not a copy.
- Q3: a date rollover making the plan stale is intended.
- Q11: the HTMX and Pico download is accepted, with sha256 in VENDORED.md.
- S6 addition: the exit test also asserts that the walkthrough's audit trail has an event for every owner action, with actor owner:1.
