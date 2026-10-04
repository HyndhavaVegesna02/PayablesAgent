# PayablesAgent

A cash-flow and payables agent for a small Indian manufacturer. It reads the
business's bank alerts, invoices and statements from email, and the bills,
photos and voice notes the owner or a helper uploads. It keeps a ledger,
plans the next 14 days of payments against a safety amount the owner sets,
and re-plans when something changes: a payment bounces, a customer pays
early, or the bank's balance stops matching the books.

**It never moves money.** The owner approves the plan in the web app and pays
from their own bank app.

The full product and build spec is
[`SME_Cash_Flow_Payables_Agent_TDD_v2.md`](SME_Cash_Flow_Payables_Agent_TDD_v2.md).

## How it is built, in one paragraph

AI reads the messy world at the edges. Gemini sorts each email, reads bank
alerts, invoices, statements, photos and voice notes into structured fields,
and works the exceptions code can't settle alone. Plain code owns every number
in the middle: rule checks on everything the AI read, a ledger that changes only
through one writer function, a reconciler, and a planner that is a pure
function. The model never calculates an authoritative value. It has no tool
that approves a payment, marks a bill paid, or sends anything outside the app.
Details, with diagrams: [docs/architecture.md](docs/architecture.md).

## Quickstart

You need Python 3.12 and [uv](https://docs.astral.sh/uv/). The commands are
for a Unix-like shell; on Windows, use Git Bash.

```sh
make setup      # virtualenv + pinned dependencies; copies .env.example to .env if there is none
make db         # applies the migrations
make reseed     # a fresh database with the worked-example business and its first plan
```

Open `.env` and set `SESSION_SECRET` (the app refuses to start without it). To
make one:

```sh
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

For the offline demo, set `DEMO_NOW=2026-10-12T09:00:00+05:30` and
`DEMO_AI=fixtures` in `.env` as well (see [Demo mode](#demo-mode)). Then, in
two terminals:

```sh
make run        # the web app on http://localhost:8000
make worker     # the job worker and scheduler
```

Log in as `owner@example.test` / `owner-demo-pass`, or as the helper,
`helper@example.test` / `helper-demo-pass`. These are dev defaults; set
`SEED_OWNER_PASSWORD` and `SEED_HELPER_PASSWORD` anywhere else.
`GET /api/health` reports the database, the queue depth and the worker's
heartbeat.

`make test` runs the whole test suite (pytest with Hypothesis properties, the
eval scenarios in fixture mode, and the import-linter contracts). It needs no
network and no API key.

## Demo mode

Demo mode replays the TDD's worked example: one week at Saraswati Precision
Works from Monday 12 October 2026, with no Gemini and no network.

- `DEMO_NOW` fixes "now" for both the web app and the worker. You move it
  forward with `make demo-time T=...`, or with the form on Settings. Each move
  checks the mail. Moving past Monday 07:00 makes that Monday's plan, as the
  real-time scheduler would.
- `DEMO_AI=fixtures` makes every AI reply a canned one from
  `fixtures/ai_replies.json`, and the app shows a banner saying so. A
  document with no canned reply is reported as AI-unavailable, never guessed.
- The mailbox is the folder `fixtures/test_inbox/`. Each email becomes visible
  once the demo clock passes its `Date:` header.

### Walkthrough

1. **Monday 09:00, the plan.** Log in as the owner. The week page shows the
   14-day plan. The lowest balance falls below the safety amount on Thu 22 Oct,
   so the plan is flagged and offers options (the TDD's worked example; eval
   scenario 11 checks its figures). Choose *ask Nandi Foods to pay early*.
   Then approve today's payments: the ₹1,80,000 to Ashirwad Paper.
2. **`make demo-time T=2026-10-12T12:00:00+05:30`.** The bank's debit alert
   for that payment arrives, is read, passes its checks and matches the
   approved payment: the bill is paid. A re-sent copy of the same alert is
   recognised as a duplicate.
3. **`make demo-time T=2026-10-13T23:00:00+05:30`.** On Tuesday, Kaveri
   Traders' payment arrives and matches what they owed. Ashirwad emails invoice
   AP/2610/131, which waits on *Needs attention*: confirm it. Its bank details
   (the account ending 4410) are Ashirwad's first, so they wait for your own
   decision: confirming a bill never approves its bank account. Approve them
   (in real life, after checking with Ashirwad on a number you already have),
   and they become Ashirwad's details on record. The
   bank's statement arrives locked. *Needs attention* asks for its password,
   which is `SPW-4821-oct` for this fictional statement. It's used once and
   never stored. After that, the statement's rows are read and checked against
   its opening and closing balances.
4. **`make demo-time T=2026-10-14T11:00:00+05:30`.** On Wednesday, the bank
   returns Monday's ₹1,80,000 payment. The bill is reopened, the plan is
   updated, and an owner alert is queued. Ashirwad also emails invoice
   AP/2610/140, which gives new bank details and tells the reader to approve
   them. The details on record (from AP/2610/131) don't change: the new ones
   are flagged as a change, and only you can accept them.
5. **`make demo-time T=2026-10-15T23:00:00+05:30`.** On Thursday a debit alert
   shows an available balance below what the ledger calculates. The reconciler
   waits for the 23:00 recheck. When the gap is still there, the account is
   marked as being checked, and the planner plans from the lower balance in
   the meantime. The fixture assistant can't explain this gap, so *Needs
   attention* asks you for the real balance. The ₹35,000 debit itself was
   never approved in the app, so it matches no payment, and you're asked
   which bill it paid.
6. **`make demo-time T=2026-10-16T11:00:00+05:30`.** On Friday, Nandi Foods'
   early payment arrives, matches what they owed, and the plan is redone with
   it. A promotional email is sorted as irrelevant and ignored.

If an approval says *the plan changed since you opened it*, that's the
stale-plan check working: approve again on the refreshed plan.

A 3-minute version for a recording is in
[docs/demo-script.md](docs/demo-script.md).

### Live AI

Outside demo mode the worker calls Gemini (`gemini-3.8-flash`, set in
`config.yaml`) with `GEMINI_API_KEY` from `.env`. Nothing in `make test` calls
it. `make smoke-gemini` makes at most 3 billed calls to check the prompts on
the real model. Run it only when someone is paying for it.

## Evidence

| What | Where |
| --- | --- |
| Architecture, with the agent loop, tools, context management and control points labelled | [docs/architecture.md](docs/architecture.md) |
| Eval report: the 11 TDD scenarios, repeated runs, three levels (end to end, path, component) | [docs/evals/](docs/evals/README.md) |
| Harness ablation: full vs bare, same model, and four knock-outs | [docs/evals/](docs/evals/README.md) |
| One regression caught | [docs/evals/](docs/evals/README.md#the-regression-told-straight-d23) |
| Two full-workflow fortnights through the real web app, worker and demo clock, step by step | [docs/evals/](docs/evals/README.md#full-workflow-runs) |
| Two traces, a success and a failure, each with a walkthrough | [docs/traces/](docs/traces/README.md) |
| Threat model, with the attack we ran and its outcome | [docs/threat-model.md](docs/threat-model.md) |
| Permission model: what the agent and each role can touch | [docs/permission-model.md](docs/permission-model.md) |
| Demo script (3 minutes) | [docs/demo-script.md](docs/demo-script.md) |

Every figure in those pages comes from a generated report or file, and names
the commit and run it came from.

### Running the evals

```sh
make evals ARGS="--ai fixtures --runs 5"            # offline, deterministic
make ablation ARGS="--ai fixtures"                  # full vs bare vs knock-outs, offline
make evals ARGS="--ai fixtures --runs 5 --config evals/variants/regress-max-steps.yaml --label regress-max-steps"
make workflow                                       # the two scripted fortnights (RUN=A|B, N=repeats)
```

Live runs add `--ai live --yes-spend`. A budget guard in code stops every
invocation at 600 model calls or 5,000,000 micro-USD (US$5), whichever comes
first. It writes a partial report marked ABORTED, runs one call at a time, and
backs off on rate limits. Reports go to `docs/evals/<date>-<mode>-<label>/`.

## Reusable components

Two pieces here are built to be lifted: the **eval harness**, which fits any agent that calls a model through
one backend interface, and **`app/validate`**, the domain rule checks for Indian business finance.

### The eval harness

- **The runner with component-tagged checks** (`evals/runner.py`, `evals/scenario.py`). A scenario is a folder
  with an `expected.yaml`: steps (deliver an email, upload a file, move the clock, press a button the page
  shows) and checks. Each check is a `SELECT` on the run's own database, tagged with the component it judges
  (`sort`, `extract`, `validate`, `reconcile`, `planner`, `agent`) and its level (`end_to_end`, or
  `trajectory` for the path: steps, refusals, escalations). A failed run names its first failing component,
  so a report says where the system broke, not just that it did.
- **Knock-out seams** (`evals/knockouts.py`). Each knock-out removes one control by patching named functions
  for one run (`applied(name, binding)`, always restored), never by a flag in app code; the report lists the
  seams it patched. Add one with a function returning `(module, attribute, replacement)` triples and an
  outcome check that detects it.
- **The budget guard** (`evals/budget.py::BudgetGuard`). It wraps the model backend for a whole invocation:
  a hard call cap and cost cap (`--max-usd` lowers it), pacing, backoff on a rate limit, an immediate stop on
  a spending cap, and a reason the report records.

**How to lift it.** Copy `evals/` and give it four things of yours: a `Backend` with one `generate(...)`
method (`app/ai/client.py`'s protocol), a function that builds a fresh world for one run (here
`evals/runner.py::fresh_world`: a migrated, seeded database), the step handlers your scenarios need
(the `STEPS` table in `evals/runner.py`), and your seams. The report writers (`evals/report.py`) and `make check-evidence`'s
re-derivation work unchanged on what they produce.

### `app/validate`

`app/validate` holds the rule checks for Indian business finance. They are pure
functions over integer paise: no I/O, no clock, no database, and nothing from
this app except `app.domain` (an import-linter contract enforces that). Another
project can lift the package with `app/domain/money.py`, `time.py` and `names.py` (all three use the
standard library only) and use it as is. `tests/test_evidence_docs.py` checks that list against the
package's imports.

- GSTIN format and its mod-36 check character
- Invoice arithmetic (items + CGST/SGST/IGST + an explicit round-off of at most ₹1)
- Statement arithmetic (opening + credits − debits = closing)
- Bank-alert, statement and invoice field checks, duplicates (through a lookup
  you pass in), and vendor bank-detail changes
- Amounts in Indian notation (`Rs.1,80,000.00`) and as spoken in Hindi,
  Hinglish or English (`dedh lakh`), read exactly, never through a float

Each check returns `passed`, `failed: <why>`, `not_applicable` or `skipped: <why>`.
`tests/test_evidence_docs.py` runs this example as written:

<!-- example: app/validate -->
```python
from app.domain.money import format_inr, parse_inr, parse_spoken_inr
from app.validate.arithmetic import check_invoice_arithmetic, check_statement_arithmetic
from app.validate.gstin import check_gstin

assert check_gstin("27ZZZFZ0001Z1ZU") == "passed"
assert check_gstin("27ZZZFZ0001Z1ZV") == "failed: 27ZZZFZ0001Z1ZV: check character should be U"

items, cgst, sgst = parse_inr("Rs.40,000"), parse_inr("Rs.3,600"), parse_inr("Rs.3,600")
assert check_invoice_arithmetic([items], [cgst, sgst], total=parse_inr("Rs.47,200")) == "passed"
assert check_invoice_arithmetic([items], [cgst, sgst], total=parse_inr("Rs.47,300")).startswith(
    "failed: items ₹40,000 + GST ₹7,200 = ₹47,200")

assert check_statement_arithmetic(opening=62_000_000, credits=[3_300_000], debits=[59_000],
                                  closing=65_241_000) == "passed"

assert parse_spoken_inr("dedh lakh") == 15_000_000          # ₹1,50,000 in paise
assert format_inr(parse_spoken_inr("sawa do lakh")) == "₹2,25,000"
```

More detail on each module is in [app/validate/README.md](app/validate/README.md).

## Known limits

- **A crash on an agent run's last attempt (CHG-026).** If the worker process
  dies during an agent case's last attempt, the job is marked dead without its
  handler running. The case isn't handed to the owner, and a drift case can
  stay CHECKING. The planner keeps using the lower balance, so the plan stays
  safe, but nobody is asked. The fix (a reaper for dead agent jobs) is in the
  backlog.
- **The live voice-note fixture is synthetic speech.** `fixtures/uploads/voice-note-sharma.wav`
  was made with Windows' built-in English voice (`scripts/make_voice_fixture.ps1`),
  so the Hindi words have English phonetics. In fixture mode its reply is
  canned. Whether Gemini can transcribe it is shown only by a live run. **If
  the live voice scenario fails on the audio, please record a 5-second clip of
  someone saying "Sharma Packaging ka bill, dedh lakh rupaye, paanch November
  tak dena hai" and replace the file.**
- **The "handwritten" bill is an italic rendering**
  (`fixtures/uploads/handwritten-bill-ganesh.png`), not real handwriting. It's
  weaker evidence than a photo of a real bill.
- **The live evidence is thinner than the fixture evidence.** The live runs on
  Gemini are in [docs/evals/](docs/evals/README.md), told in order: the TDD's
  scenarios five times each (one combined page), both scripted fortnights, the
  ablation and the degraded prompt. They are one model, a few runs each, and the
  ablation one run per scenario. The three harder scenarios (12 to 14) are
  fixture-only and have not run live. In the fixture ablation, the bare harness
  and the no-planner knock-out are marked *mechanics only*: only the live one
  scores them.
- **A tax payment matches only if its debit names the tax office.** A PF, ESI
  or GST bill has no vendor, so its debit is matched by payee words per tax
  type (`matching.statutory_payees` in `config.yaml`: EPFO, ESIC, GST, CBIC
  and so on), with the same amount and dates (CHG-028). A debit whose
  description names none of them, such as a bank's generic "tax payment", goes
  to *Needs attention* as "which bill did this debit pay?". Run A takes both
  paths.
- **The voice amount check reads form, not meaning (PO D30).** Code passes a
  voice bill's amount only when the transcript says exactly one amount and it
  equals the model's. It can't tell a total from a part by meaning ("baaki
  dedh lakh"), a tail after another word ("ek lakh hai, pachaas"), a comma
  merge, or a spelling or guess word it has no list for. The owner confirms
  every voice bill with the transcript beside the amount.
- **A final answer's evidence rule checks where the evidence came from, not
  whether the answer is true.** A hijacked model can still write a false
  summary. It's shown as the assistant's own words and changes nothing; see
  [docs/threat-model.md](docs/threat-model.md).

## Gmail

*Placeholder.* Gmail integration (read-only OAuth, filtered to known bank and
vendor senders, and the refresh token encrypted at rest) is owned by the
repository's owner and is not part of this build. Until it lands, mail is read
from a folder of `.eml` files (`MAIL_SOURCE=eml_folder`,
`TEST_INBOX_PATH=./fixtures/test_inbox`). Code reaches the mailbox only through
the `MailSource` interface (`app/ingest/mail_source.py`), so a `GmailSource`
plugs in there.

## Repository layout

| Path | What |
| --- | --- |
| `app/ai/` | Gemini calls: sort, extract, explain, one agent step. Never imports the ledger, the database or the web app |
| `app/agent/` | the exception agent: case file, tools, loop, escalation |
| `app/validate/` | the rule checks (pure) |
| `app/ledger/` | the writer (the only code that changes ledger state) and the reconciler |
| `app/planner/` | the 14-day planner (a pure function) |
| `app/ingest/` | the mail source and the document pipeline |
| `app/jobs/`, `app/worker.py` | the job queue and its handlers |
| `app/notify/` | owner alerts: fixed templates and SMTP |
| `app/web/` | the owner web app (FastAPI, Jinja, HTMX, Pico.css) |
| `evals/` | the eval runner, scenarios, report, budget guard and ablation |
| `fixtures/` | the worked example's seed, the test inbox, uploads and canned AI replies |
| `docs/` | the evidence above, plus batch plans and reviews |

The project is built in reviewed batches (`.yourteam/`, `docs/batches/`).
